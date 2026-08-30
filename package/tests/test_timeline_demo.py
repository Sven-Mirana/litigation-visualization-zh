"""GPL-3.0-only. Standalone fail-closed tests for the fixed synthetic demo.

Run with the external requirements-timeline-demo.txt environment and python -B.
TIMELINE_DEMO_TEST_ENGINE is a test-only read-only engine-location override for
an unassembled overlay; the shipped CLI has no environment or input override.
"""
from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
from timeline_demo import demo


def source_inventory(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): demo.digest(p.read_bytes()) for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts}


class FixedTimelineDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("TIMELINE_DEMO_TEST_ENGINE"):
            demo.ENGINE_ROOT = Path(os.environ["TIMELINE_DEMO_TEST_ENGINE"]).resolve()
        demo.bound_sources()
        demo.runtime_check()
        cls.temporary = tempfile.TemporaryDirectory(prefix="timeline-demo-tests-")
        cls.root = Path(cls.temporary.name).resolve()
        cls.source_before = source_inventory(demo.ENGINE_ROOT)
        cls.package_before = source_inventory(PACKAGE)
        cls.fixture_before = demo.FIXTURE.read_bytes()
        cls.baseline = cls.root / "baseline"
        demo.run_demo(cls.baseline)

    @classmethod
    def tearDownClass(cls):
        try:
            if source_inventory(demo.ENGINE_ROOT) != cls.source_before or source_inventory(PACKAGE) != cls.package_before or demo.FIXTURE.read_bytes() != cls.fixture_before:
                raise AssertionError("read-only source changed during tests")
        finally:
            cls.temporary.cleanup()

    def fresh(self, name):
        return self.root / self._testMethodName / name

    def parent(self):
        parent = self.root / self._testMethodName
        parent.mkdir()
        return parent

    def test_two_runs_are_identical_and_sources_unchanged(self):
        parent = self.parent()
        out = parent / "second"
        result = demo.run_demo(out)
        self.assertEqual(demo.inventory(out), demo.inventory(self.baseline))
        self.assertEqual(result["status"], "PASS_FIXED_SYNTHETIC_DEMO_ONLY")
        self.assertEqual(len(result["artifacts"]), 7)
        self.assertEqual(source_inventory(demo.ENGINE_ROOT), self.source_before)
        self.assertEqual(demo.FIXTURE.read_bytes(), self.fixture_before)

    def test_exact_approved_bytes_and_native_scope(self):
        result = demo.verify_demo(self.baseline)
        for name, expected in demo.ARTIFACT_HASHES.items():
            self.assertEqual(demo.digest((self.baseline / name).read_bytes()), expected)
        self.assertEqual(result["artifacts"][-1]["native_object_count"], 51)
        self.assertFalse(result["drawio_renderer_qa_replayed"])
        self.assertFalse(result["geometry_qa_replayed"])

    def test_engine_uses_private_namespace_not_production_imports(self):
        modules = demo.engine_modules()
        self.assertTrue(all(m.__name__.startswith("timeline_demo._fixed_r2_client_delivery.") for m in modules))
        self.assertNotIn("client_delivery", sys.modules)

    def test_fixture_tamper_is_rejected_before_any_output(self):
        parent = self.parent()
        fixture = parent / "fixture" / "fixture.json"
        fixture.parent.mkdir()
        fixture.write_bytes(self.fixture_before + b" ")
        with mock.patch.object(demo, "FIXTURE", fixture):
            with self.assertRaisesRegex(demo.DemoError, "FIXED_SYNTHETIC_IR_HASH_MISMATCH"):
                demo.run_demo(parent / "output")
        self.assertEqual({p.name for p in parent.iterdir()}, {"fixture"})

    def test_engine_tamper_is_rejected_before_any_output(self):
        parent = self.parent()
        engine = parent / "engine"
        for relative in demo.SOURCE_HASHES:
            dest = engine / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(demo.ENGINE_ROOT / relative, dest)
        with (engine / "client_delivery/pptx_writer.py").open("ab") as handle:
            handle.write(b"\n# changed\n")
        with mock.patch.object(demo, "ENGINE_ROOT", engine):
            with self.assertRaisesRegex(demo.DemoError, "BOUND_ENGINE_SOURCE_DRIFT"):
                demo.run_demo(parent / "output")
        self.assertEqual({p.name for p in parent.iterdir()}, {"engine"})

    def test_missing_dependency_is_zero_output(self):
        parent = self.parent()
        with mock.patch.object(demo, "runtime_check", side_effect=demo.DemoError("DEMO_DEPENDENCY_MISSING")):
            with self.assertRaisesRegex(demo.DemoError, "DEMO_DEPENDENCY_MISSING"):
                demo.run_demo(parent / "output")
        self.assertEqual(list(parent.iterdir()), [])

    def test_partial_writer_failure_is_zero_output_and_zero_stage(self):
        parent = self.parent()
        def broken(stage, transient, ir, raw, modules):
            stage.mkdir(exist_ok=True)
            (stage / "partial.pptx").write_bytes(b"not a deck")
            raise demo.DemoError("INJECTED_LATE_WRITER_FAILURE")
        with mock.patch.object(demo, "render_stage", side_effect=broken):
            with self.assertRaisesRegex(demo.DemoError, "INJECTED_LATE_WRITER_FAILURE"):
                demo.run_demo(parent / "output")
        self.assertEqual(list(parent.iterdir()), [])

    def test_postreceipt_failure_is_zero_output_and_zero_stage(self):
        parent = self.parent()
        def staged(stage, transient, ir, raw, modules):
            shutil.copytree(self.baseline, stage, dirs_exist_ok=True)
        with mock.patch.object(demo, "render_stage", side_effect=staged), mock.patch.object(demo, "verify_demo", side_effect=demo.DemoError("INJECTED_POSTRECEIPT_FAILURE")):
            with self.assertRaisesRegex(demo.DemoError, "INJECTED_POSTRECEIPT_FAILURE"):
                demo.run_demo(parent / "output")
        self.assertEqual(list(parent.iterdir()), [])

    def test_existing_output_is_never_replaced(self):
        parent = self.parent()
        out = parent / "output"
        out.mkdir()
        sentinel = out / "user-file"
        sentinel.write_bytes(b"preserve")
        with self.assertRaisesRegex(demo.DemoError, "OUTPUT_ALREADY_EXISTS"):
            demo.run_demo(out)
        self.assertEqual(sentinel.read_bytes(), b"preserve")

    def test_atomic_noreplace_refuses_racing_empty_directory(self):
        parent = self.parent()
        source, target = parent / "stage", parent / "target"
        source.mkdir()
        (source / "artifact").write_bytes(b"stage")
        target.mkdir()
        before = target.stat().st_ino
        with self.assertRaises(OSError):
            demo.rename_new(source, target)
        self.assertEqual(target.stat().st_ino, before)
        self.assertEqual(list(target.iterdir()), [])
        self.assertEqual((source / "artifact").read_bytes(), b"stage")

    def test_output_symlink_and_symlink_parent_are_rejected(self):
        parent = self.parent()
        real = parent / "real"
        real.mkdir()
        link = parent / "link"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(demo.DemoError, "OUTPUT_SYMLINK_ANCESTOR"):
            demo.run_demo(link / "output")
        with self.assertRaisesRegex(demo.DemoError, "OUTPUT_SYMLINK_ANCESTOR"):
            demo.run_demo(link)
        self.assertEqual(list(real.iterdir()), [])

    def test_no_real_case_or_profile_input_flags(self):
        parent = self.parent()
        for flag in ("--input", "--ir", "--case-id", "--timeline-profile", "--source-dir"):
            with self.subTest(flag=flag), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    demo.main(["--out", str(parent / "output"), flag, "anything"])
                self.assertEqual(caught.exception.code, 2)
        self.assertEqual(list(parent.iterdir()), [])

    def test_output_inside_package_is_rejected(self):
        with self.assertRaisesRegex(demo.DemoError, "OUTPUT_INSIDE_SOURCE_PACKAGE"):
            demo.checked_output(demo.PACKAGE_ROOT / "forbidden-demo-output")

    def test_artifact_map_and_receipt_tamper_are_rejected(self):
        parent = self.parent()
        filenames = ["timeline-profile-a.REVIEW-DRAFT.html", "timeline-r2-comparison.REVIEW-DRAFT.drawio", demo.MAP_OUTPUT, demo.RECEIPT, demo.IR_OUTPUT]
        for index, name in enumerate(filenames):
            with self.subTest(file=name):
                out = parent / str(index)
                shutil.copytree(self.baseline, out)
                with (out / name).open("ab") as handle:
                    handle.write(b" ")
                with self.assertRaises(demo.DemoError):
                    demo.verify_demo(out)

    def test_artifact_symlink_is_rejected(self):
        parent = self.parent()
        out = parent / "tampered"
        shutil.copytree(self.baseline, out)
        name = "timeline-profile-control.REVIEW-DRAFT.pptx"
        (out / name).unlink()
        (out / name).symlink_to(self.baseline / name)
        with self.assertRaisesRegex(demo.DemoError, "MISSING_OR_UNSAFE_BOUND_FILE"):
            demo.verify_demo(out)


if __name__ == "__main__":
    unittest.main()
