#!/usr/bin/env python3
"""Synthetic-only S1 regression tests for the 07-only visualization runner."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


sys.dont_write_bytecode = True
CANDIDATE = Path(__file__).resolve().parents[1]
PACKAGE = CANDIDATE / "package"
BASE_MD = PACKAGE / "fixtures/sample-case/07-诉讼案件办案方案工作底稿.md"
RUNNER_PATH = PACKAGE / "tools/run_vis.py"
BUILDER_PATH = PACKAGE / "viz-engine/mother-build_t4.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


builder = load_module("s1_test_builder", BUILDER_PATH)
runner = load_module("s1_test_runner", RUNNER_PATH)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_section(text: str, title: str, body: str) -> str:
    pattern = re.compile(
        rf"(^## {re.escape(title)}\n).*?(?=^## |\Z)", re.MULTILINE | re.DOTALL
    )
    replacement = rf"\1\n{body.strip()}\n\n"
    updated, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise AssertionError(f"section not found: {title}")
    return updated


def timeline_text(lines: list[str]) -> str:
    text = BASE_MD.read_text(encoding="utf-8")
    bodies = {
        builder.ANCHOR_TITLES[1]: "\n".join(lines),
        builder.ANCHOR_TITLES[2]: "合成未系日期履行事实。",
        builder.ANCHOR_TITLES[3]: "合成未系日期款项事实。",
        builder.ANCHOR_TITLES[4]: "合成未系日期通知事实。",
    }
    for title, body in bodies.items():
        text = replace_section(text, title, body)
    return text


class FakeChrome:
    def __init__(self, *, fail_at=None, no_write_at=None, timeout_at=None, on_call=None,
                 png_size=(1600, 900)):
        self.fail_at = fail_at
        self.no_write_at = no_write_at
        self.timeout_at = timeout_at
        self.on_call = on_call
        self.png_size = png_size
        self.calls = 0
        self.screenshots: list[Path] = []

    def __call__(self, argv, **_kwargs):
        self.calls += 1
        screenshot_arg = next(arg for arg in argv if str(arg).startswith("--screenshot="))
        screenshot = Path(str(screenshot_arg).split("=", 1)[1])
        self.screenshots.append(screenshot)
        if self.on_call:
            self.on_call(self.calls)
        if self.timeout_at == self.calls:
            raise subprocess.TimeoutExpired(argv, 120)
        if self.fail_at == self.calls:
            return SimpleNamespace(returncode=9)
        if self.no_write_at != self.calls:
            screenshot.write_bytes(
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
                + struct.pack(">II", *self.png_size)
                + b"SYNTHETIC-S1"
            )
        return SimpleNamespace(returncode=0)


class S1TestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lv-s1-synthetic-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make_case(self, text: str | None = None, *, nested: bool = False):
        frozen = self.root / "frozen07"
        frozen.mkdir()
        if nested:
            md = frozen / "content/07.md"
            md.parent.mkdir()
            relpath = "content/07.md"
        else:
            md = frozen / "07-诉讼案件办案方案工作底稿.md"
            relpath = md.name
        md.write_text(text or BASE_MD.read_text(encoding="utf-8"), encoding="utf-8")
        manifest = frozen / "FROZEN-07-MANIFEST.json"
        manifest.write_text(
            json.dumps(
                {"case_id": "S1-SYNTHETIC", "md_relpath": relpath, "md_sha256": sha256(md)},
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        receipt = self.root / "TEXT-PASS-RECEIPT.json"
        receipt.write_text(
            json.dumps({"result": "PASS", "case_id": "S1-SYNTHETIC"}) + "\n",
            encoding="utf-8",
        )
        return frozen, md, manifest, receipt

    def invoke(self, frozen: Path, receipt: Path, out: Path, fake=None, extra=None):
        argv = [
            str(RUNNER_PATH), "--enable-vis", "--case-id", "S1-SYNTHETIC",
            "--frozen07-dir", str(frozen), "--text-pass-receipt", str(receipt),
            "--out", str(out),
        ]
        if extra:
            argv.extend(extra)
        capture = io.StringIO()
        patcher = mock.patch.object(runner.subprocess, "run", fake or FakeChrome())
        with mock.patch.object(sys, "argv", argv), patcher, contextlib.redirect_stdout(capture):
            code = runner.main()
        return code, capture.getvalue()

    def assert_no_staging(self, out: Path):
        self.assertEqual(list(out.parent.glob(f".{out.name}.staging-*")), [])


class DateParsingTests(S1TestCase):
    def test_mixed_dates_are_iso_sorted_and_source_text_is_preserved(self):
        text = timeline_text([
            "1. 2014年10月1日 事件十月",
            "2. 2014年4月30日 事件四月甲",
            "3. 合同于2015-1-2签订",
            "4. 2014-4-30 事件四月乙",
        ])
        result, error = builder.build_case_views(text, "S1")
        self.assertIsNone(error)
        events = result["views"]["02-关键事件时间线"]["events"]
        self.assertEqual([e["date"] for e in events], [
            "2014-04-30", "2014-04-30", "2014-10-01", "2015-01-02"
        ])
        self.assertEqual(events[0]["text"], "2014年4月30日 事件四月甲")
        self.assertEqual(events[1]["text"], "2014-4-30 事件四月乙")
        self.assertEqual(events[3]["text"], "合同于2015-1-2签订")

    def test_same_day_keeps_source_order_and_first_date_only(self):
        text = timeline_text([
            "1. 2024-2-15 同日甲，复核于2024-3-1",
            "2. 2024-2-15 同日乙",
            "3. 2024-2-15 同日丙",
        ])
        result, error = builder.build_case_views(text, "S1")
        self.assertIsNone(error)
        events = result["views"]["02-关键事件时间线"]["events"]
        self.assertEqual([e["text"] for e in events], [
            "2024-2-15 同日甲，复核于2024-3-1", "2024-2-15 同日乙", "2024-2-15 同日丙"
        ])

    def test_invalid_calendar_date_fails_closed(self):
        for invalid in ("2014-02-30", "2014-13-01"):
            with self.subTest(invalid=invalid):
                result, error = builder.build_case_views(timeline_text([f"1. {invalid} 非法"]), "S1")
                self.assertIsNone(result)
                self.assertEqual(error, f"非法日期:{invalid}")

    def test_mixed_date_separators_fail_closed(self):
        for invalid in ("2024年1-2", "2024-1月2"):
            with self.subTest(invalid=invalid):
                result, error = builder.build_case_views(timeline_text([f"1. {invalid} 非法"]), "S1")
                self.assertIsNone(result)
                self.assertEqual(error, f"非法日期格式:{invalid}")

    def test_event_limit_is_explicit_not_silent(self):
        fourteen = [f"{i}. 2024-01-{i:02d} 事件{i}" for i in range(1, 15)]
        result, error = builder.build_case_views(timeline_text(fourteen), "S1")
        self.assertIsNone(error)
        self.assertEqual(len(result["views"]["02-关键事件时间线"]["events"]), 14)
        result, error = builder.build_case_views(
            timeline_text(fourteen + ["15. 2024-01-15 事件15"]), "S1"
        )
        self.assertIsNone(result)
        self.assertEqual(error, "事件数15超过上限14")

    def test_chain_list_marker_does_not_strip_year(self):
        text = timeline_text(["2. 2014年4月30日 合成交易链"])
        result, error = builder.build_case_views(text, "S1")
        self.assertIsNone(error)
        chain = result["views"]["01-主体关系图"]["chain"]
        self.assertEqual(chain[0]["text"], "2014年4月30日 合成交易链")


class RunnerBoundaryTests(S1TestCase):
    def test_positive_is_atomic_and_exact(self):
        frozen, _md, _manifest, receipt = self.make_case()
        out = self.root / "out"
        fake = FakeChrome()
        code, stdout = self.invoke(frozen, receipt, out, fake)
        self.assertEqual(code, 0)
        self.assertIn("VALID: S1-SYNTHETIC 4SVG+4PNG", stdout)
        self.assertEqual(fake.calls, 4)
        self.assertTrue(all(".out.staging-" in str(path.parent) for path in fake.screenshots))
        expected = {
            f"{name}{suffix}" for name, _renderer in runner.VIEW_RENDERERS
            for suffix in (".svg", ".png")
        }
        self.assertEqual({p.name for p in out.iterdir()}, expected)
        self.assertTrue(all(p.is_file() and not p.is_symlink() and p.stat().st_size for p in out.iterdir()))
        self.assert_no_staging(out)

    def test_staging_extra_directory_fails_closed(self):
        frozen, _md, _manifest, receipt = self.make_case()
        out = self.root / "out"

        def inject_directory(call):
            if call == 4:
                fake.screenshots[-1].parent.joinpath("unexpected-dir").mkdir()

        fake = FakeChrome(on_call=inject_directory)
        code, stdout = self.invoke(frozen, receipt, out, fake)
        self.assertEqual(code, 3)
        self.assertIn("产物集合不闭合", stdout)
        self.assertFalse(out.exists())
        self.assert_no_staging(out)

    def test_validated_byte_snapshot_is_used_after_source_changes(self):
        frozen, md, _manifest, receipt = self.make_case()
        out = self.root / "out"
        original_load = runner.load
        mutated = False

        def mutate_during_load(name, path):
            nonlocal mutated
            if name == "build_t4" and not mutated:
                changed = md.read_text(encoding="utf-8").replace(
                    "## 第三节　履行与交付链",
                    "2099-12-31 RACE-INJECTED\n\n## 第三节　履行与交付链",
                )
                md.write_text(changed, encoding="utf-8")
                mutated = True
            return original_load(name, path)

        with mock.patch.object(runner, "load", side_effect=mutate_during_load):
            code, _stdout = self.invoke(frozen, receipt, out)
        self.assertEqual(code, 0)
        self.assertNotIn("RACE-INJECTED", (out / "02-关键事件时间线.svg").read_text(encoding="utf-8"))

    def test_non_utf8_input_fails_closed(self):
        frozen, md, manifest, receipt = self.make_case()
        md.write_bytes(b"\xff\xfe\x00")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["md_sha256"] = sha256(md)
        manifest.write_text(json.dumps(data) + "\n", encoding="utf-8")
        fake = FakeChrome()
        out = self.root / "out"
        code, stdout = self.invoke(frozen, receipt, out, fake)
        self.assertEqual(code, 3)
        self.assertIn("不是有效UTF-8", stdout)
        self.assertEqual(fake.calls, 0)
        self.assertFalse(out.exists())

    def test_existing_empty_output_remains_compatible(self):
        frozen, _md, _manifest, receipt = self.make_case()
        out = self.root / "out"
        out.mkdir()
        code, _stdout = self.invoke(frozen, receipt, out)
        self.assertEqual(code, 0)
        self.assertEqual(len(list(out.iterdir())), 8)

    def test_nonempty_output_is_untouched_and_renderer_not_called(self):
        frozen, _md, _manifest, receipt = self.make_case()
        out = self.root / "out"
        out.mkdir()
        stale = out / "01-主体关系图.png"
        stale.write_bytes(b"STALE")
        fake = FakeChrome()
        code, stdout = self.invoke(frozen, receipt, out, fake)
        self.assertEqual(code, 3)
        self.assertIn("拒绝复用旧产物", stdout)
        self.assertEqual(fake.calls, 0)
        self.assertEqual(stale.read_bytes(), b"STALE")

    def test_renderer_failure_or_missing_png_leaves_no_output(self):
        for fake in (FakeChrome(fail_at=3), FakeChrome(no_write_at=2),
                     FakeChrome(timeout_at=2), FakeChrome(png_size=(800, 600))):
            with self.subTest(fake=fake.__dict__):
                case_root = self.root / f"case-{id(fake)}"
                case_root.mkdir()
                prior_root = self.root
                self.root = case_root
                try:
                    frozen, _md, _manifest, receipt = self.make_case()
                    out = self.root / "out"
                    code, _stdout = self.invoke(frozen, receipt, out, fake)
                    self.assertEqual(code, 3)
                    self.assertFalse(out.exists())
                    self.assert_no_staging(out)
                finally:
                    self.root = prior_root

    def test_concurrent_nonempty_output_blocks_commit(self):
        frozen, _md, _manifest, receipt = self.make_case()
        out = self.root / "out"

        def intrude(call):
            if call == 4:
                out.mkdir()
                (out / "intruder.txt").write_text("KEEP", encoding="utf-8")

        fake = FakeChrome(on_call=intrude)
        code, stdout = self.invoke(frozen, receipt, out, fake)
        self.assertEqual(code, 3)
        self.assertIn("输出提交前状态变化", stdout)
        self.assertEqual((out / "intruder.txt").read_text(encoding="utf-8"), "KEEP")
        self.assert_no_staging(out)

    def test_relative_escape_absolute_and_symlink_are_rejected(self):
        for mode in ("escape", "absolute", "symlink"):
            with self.subTest(mode=mode):
                case_root = self.root / mode
                case_root.mkdir()
                prior_root = self.root
                self.root = case_root
                try:
                    frozen, md, manifest, receipt = self.make_case()
                    outside = self.root / "outside.md"
                    outside.write_text(md.read_text(encoding="utf-8"), encoding="utf-8")
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                    if mode == "escape":
                        data["md_relpath"] = "../outside.md"
                    elif mode == "absolute":
                        data["md_relpath"] = str(outside)
                    else:
                        link = frozen / "linked.md"
                        link.symlink_to(outside)
                        data["md_relpath"] = link.name
                    data["md_sha256"] = sha256(outside)
                    manifest.write_text(json.dumps(data) + "\n", encoding="utf-8")
                    out = self.root / "out"
                    code, _stdout = self.invoke(frozen, receipt, out)
                    self.assertEqual(code, 3)
                    self.assertFalse(out.exists())
                finally:
                    self.root = prior_root

    def test_nul_relative_path_is_rejected_without_traceback(self):
        frozen, _md, manifest, receipt = self.make_case()
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["md_relpath"] = "bad\x00path.md"
        manifest.write_text(json.dumps(data) + "\n", encoding="utf-8")
        fake = FakeChrome()
        out = self.root / "out"
        code, stdout = self.invoke(frozen, receipt, out, fake)
        self.assertEqual(code, 3)
        self.assertIn("md_relpath无效", stdout)
        self.assertEqual(fake.calls, 0)
        self.assertFalse(out.exists())

    def test_legal_nested_path_and_prefix_sibling_output(self):
        frozen, _md, _manifest, receipt = self.make_case(nested=True)
        out = self.root / "package-output"
        code, _stdout = self.invoke(frozen, receipt, out)
        self.assertEqual(code, 0)
        self.assertEqual(len(list(out.iterdir())), 8)
        self.assertFalse(runner.within(Path("/tmp/package-output"), Path("/tmp/package")))

    @unittest.skipUnless(Path("/users").exists(), "requires case-insensitive macOS filesystem")
    def test_case_variant_package_output_is_rejected(self):
        frozen, _md, _manifest, receipt = self.make_case()
        case_variant = Path(str(PACKAGE).replace("/Users/", "/users/", 1)) / "s1-forbidden-output"
        fake = FakeChrome()
        code, stdout = self.invoke(frozen, receipt, case_variant, fake)
        self.assertEqual(code, 3)
        self.assertIn("--out须在包外", stdout)
        self.assertEqual(fake.calls, 0)

    def test_package_internal_output_is_rejected(self):
        frozen, _md, _manifest, receipt = self.make_case()
        out = PACKAGE / "s1-forbidden-output"
        self.assertFalse(out.exists())
        fake = FakeChrome()
        code, stdout = self.invoke(frozen, receipt, out, fake)
        self.assertEqual(code, 3)
        self.assertIn("--out须在包外", stdout)
        self.assertEqual(fake.calls, 0)
        self.assertFalse(out.exists())

    def test_unresolvable_output_paths_fail_closed(self):
        frozen, _md, _manifest, receipt = self.make_case()
        loop = self.root / "loop"
        loop.symlink_to(loop.name)
        for raw_out in (str(loop / "out"), "~__lv_s1_user_does_not_exist__/out"):
            with self.subTest(raw_out=raw_out):
                fake = FakeChrome()
                code, stdout = self.invoke(frozen, receipt, Path(raw_out), fake)
                self.assertEqual(code, 3)
                self.assertIn("--out路径不可解析", stdout)
                self.assertEqual(fake.calls, 0)

    def test_unresolvable_frozen_directory_fails_closed(self):
        _frozen, _md, _manifest, receipt = self.make_case()
        loop = self.root / "frozen-loop"
        loop.symlink_to(loop.name)
        fake = FakeChrome()
        out = self.root / "out"
        code, stdout = self.invoke(loop, receipt, out, fake)
        self.assertEqual(code, 3)
        self.assertIn("冻结07目录", stdout)
        self.assertEqual(fake.calls, 0)

    def test_atomic_replace_failure_cleans_staging(self):
        frozen, _md, _manifest, receipt = self.make_case()
        out = self.root / "out"
        with mock.patch.object(runner.os, "replace", side_effect=OSError("synthetic")):
            code, stdout = self.invoke(frozen, receipt, out)
        self.assertEqual(code, 3)
        self.assertIn("输出原子提交失败", stdout)
        self.assertFalse(out.exists())
        self.assert_no_staging(out)

    def test_invalid_date_and_overflow_leave_zero_output(self):
        cases = [
            timeline_text(["1. 2024-02-30 非法日期"]),
            timeline_text([f"{i}. 2024-01-{i:02d} 事件{i}" for i in range(1, 16)]),
        ]
        for index, text in enumerate(cases):
            with self.subTest(index=index):
                case_root = self.root / f"parse-{index}"
                case_root.mkdir()
                prior_root = self.root
                self.root = case_root
                try:
                    frozen, _md, _manifest, receipt = self.make_case(text)
                    out = self.root / "out"
                    fake = FakeChrome()
                    code, stdout = self.invoke(frozen, receipt, out, fake)
                    self.assertEqual(code, 3)
                    self.assertIn("07解析失败", stdout)
                    self.assertFalse(out.exists())
                    self.assertEqual(fake.calls, 0)
                finally:
                    self.root = prior_root

    def test_existing_legacy_gates_are_retained(self):
        frozen, md, manifest, receipt = self.make_case()
        out = self.root / "out"
        with mock.patch.object(sys, "argv", [str(RUNNER_PATH)]), contextlib.redirect_stdout(io.StringIO()) as buf:
            self.assertEqual(runner.main(), 3)
            self.assertIn("VIS默认关闭", buf.getvalue())

        receipt.write_text(json.dumps({"result": "PASS", "case_id": "OTHER"}) + "\n", encoding="utf-8")
        code, stdout = self.invoke(frozen, receipt, out)
        self.assertEqual(code, 3)
        self.assertIn("TEXT收据跨案", stdout)

        receipt.write_text(json.dumps({"result": "PASS", "case_id": "S1-SYNTHETIC"}) + "\n", encoding="utf-8")
        md.write_text(md.read_text(encoding="utf-8") + "\n篡改", encoding="utf-8")
        code, stdout = self.invoke(frozen, receipt, out)
        self.assertEqual(code, 3)
        self.assertIn("冻结07哈希不符", stdout)

        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["md_sha256"] = sha256(md)
        manifest.write_text(json.dumps(data) + "\n", encoding="utf-8")
        md.write_text(md.read_text(encoding="utf-8").replace("## 第九节　风险与暂停事项", "## 第九节缺失"), encoding="utf-8")
        data["md_sha256"] = sha256(md)
        manifest.write_text(json.dumps(data) + "\n", encoding="utf-8")
        code, stdout = self.invoke(frozen, receipt, out)
        self.assertEqual(code, 3)
        self.assertIn("07解析失败:缺节", stdout)

    def test_missing_argument_returns_usage_exit_two(self):
        with mock.patch.object(sys, "argv", [str(RUNNER_PATH), "--enable-vis"]), contextlib.redirect_stdout(io.StringIO()) as buf:
            self.assertEqual(runner.main(), 2)
            self.assertIn("唯一公开runner", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
