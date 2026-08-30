"""GPL-3.0-only. Exact-byte-bound synthetic r2 demonstration transaction.

This is not a general timeline API. The only accepted input is the packaged,
approved three-event synthetic DeliveryIR; production delivery is untouched.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import types
import xml.etree.ElementTree as ET
import zipfile

sys.dont_write_bytecode = True
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
ENGINE_ROOT = PACKAGE_ROOT / "timeline_demo" / "r2_engine"
FIXTURE = PACKAGE_ROOT / "fixtures" / "timeline-demo" / "delivery-ir.json"
IR_SHA256 = "9a5d162d532133c32877bc32c2d5add9ada348f3ff971b61e3c1424f3123b894"
PROFILES = {"control": "legacy-rail-card", "a": "horizon-axis", "b": "docket-register"}
SOURCE_HASHES = {
    "client_delivery/__init__.py": "3f466e99a6b0110a5e400be7485db5e70eadd3411c48534391cdac1d74d7a8bd",
    "client_delivery/delivery_ir.py": "17f04ebbd6059f54dc39fd7101d8801b94416c858f891753eb258185ab4a2730",
    "client_delivery/html_writer.py": "58c2e56d6c71b945dc46c96b4a462708fd5008d56c3bfe06511b4c5b803be6bc",
    "client_delivery/input_gate.py": "40e868a754e44f69ed98b2d5814eb8fe97473b03802fd26b8c824245727019f0",
    "client_delivery/pptx_writer.py": "6cea0fe3ba4bde9fcdd080fc2edbd960a03595ba16900e5648a5da49f30a6fb0",
    "client_delivery/semantic_inventory.py": "04a998fd9a659710467703ce19af3a8a41b010e3c2aec5ecc317b041a252599d",
    "client_delivery/verify.py": "d8730e3b34c6affa5b48e33904cddf385f23dd8c8298ee98f99e76d1296395cb",
}
RUNTIME = {"python-pptx": "1.0.2", "Pillow": "12.3.0", "lxml": "6.1.1", "XlsxWriter": "3.2.9", "typing_extensions": "4.16.0"}
ARTIFACT_HASHES = {
    "timeline-profile-control.REVIEW-DRAFT.pptx": "46b8b6ba09170ced29ed40b6813c5107cf44c167f3b498a8288eda6ae9724296",
    "timeline-profile-control.REVIEW-DRAFT.html": "94cc0b3e2adcc4d245a98c4cdfb295f107da8745549906696ce65085588d6044",
    "timeline-profile-a.REVIEW-DRAFT.pptx": "f1b24d0c987d9f5cfe6dde818e293ee8273c38a862b70f87c4f3c5e8a34f74da",
    "timeline-profile-a.REVIEW-DRAFT.html": "4c906a288ffd222ca0b39e5e98adb0127eaf80b185b9e24cf4167241c84bee32",
    "timeline-profile-b.REVIEW-DRAFT.pptx": "f57245e7d04733e88a240663bce2df0a32fc1ea0ae82d152e58db7c4cfc63a5b",
    "timeline-profile-b.REVIEW-DRAFT.html": "027c29c979f015878352cb8037630102ad264519a9b0897270291dda488ebf1a",
    "timeline-r2-comparison.REVIEW-DRAFT.drawio": "95e4f0c56dc998c4d3d5584ce2a08168cc397aed86d233c614e98ff05d3a7cdc",
}
RECEIPT = "TIMELINE-DEMO-RECEIPT.json"
IR_OUTPUT = "internal-audit/delivery-ir.json"
MAP_OUTPUT = "drawio-export-map.json"
NS = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main"}


class DemoError(ValueError):
    """Stable fail-closed demo error, never a production release receipt."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise DemoError(code)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def read_regular(path: Path) -> bytes:
    require(not path.is_symlink() and path.is_file(), "MISSING_OR_UNSAFE_BOUND_FILE")
    return path.read_bytes()


def fixed_ir() -> tuple[dict, bytes]:
    require(not FIXTURE.parent.is_symlink() and not FIXTURE.parent.parent.is_symlink(), "FIXTURE_SYMLINK_ANCESTOR")
    raw = read_regular(FIXTURE)
    require(digest(raw) == IR_SHA256, "FIXED_SYNTHETIC_IR_HASH_MISMATCH")
    ir = json.loads(raw)
    require(ir["data_class"] == "synthetic" and ir["release_state"] == "REVIEW_DRAFT", "FIXTURE_SCOPE_DRIFT")
    timelines = [s for s in ir["slides"] if s["role"] == "timeline"]
    require(len(timelines) == 1 and timelines[0]["slide_id"] == "timeline-01", "FIXTURE_TIMELINE_DRIFT")
    require(len(timelines[0]["content"]["events"]) == 3 and not timelines[0]["content"]["undated_milestones"], "FIXTURE_EVENT_COUNT_DRIFT")
    require(len(ir["slides"]) == 13 and len(ir["semantic_inventory"]) == 47, "FIXTURE_INVENTORY_DRIFT")
    return ir, raw


def bound_sources() -> dict[str, str]:
    require(not ENGINE_ROOT.is_symlink() and ENGINE_ROOT.is_dir(), "ISOLATED_R2_ENGINE_MISSING")
    result = {}
    for relative, expected in SOURCE_HASHES.items():
        path = ENGINE_ROOT / relative
        require(not path.parent.is_symlink(), "BOUND_SOURCE_SYMLINK")
        actual = digest(read_regular(path))
        require(actual == expected, "BOUND_ENGINE_SOURCE_DRIFT:" + relative)
        result[relative] = actual
    fixed_ir()
    return result


def runtime_check() -> None:
    for name, expected in RUNTIME.items():
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise DemoError("DEMO_DEPENDENCY_MISSING:" + name) from exc
        require(actual == expected, "DEMO_DEPENDENCY_VERSION_MISMATCH:" + name)


def engine_modules() -> tuple:
    """Execute hash-checked source under a private namespace, never stale pyc.

    All relative dependencies in this closed seven-file engine are loaded in
    dependency order. Neither sys.path nor the production client_delivery
    package namespace is changed.
    """
    bound_sources()
    namespace = "timeline_demo._fixed_r2_client_delivery"
    package = types.ModuleType(namespace)
    package.__package__ = namespace
    package.__path__ = [str(ENGINE_ROOT / "client_delivery")]
    package.__file__ = str(ENGINE_ROOT / "client_delivery/__init__.py")
    sys.modules[namespace] = package
    loaded = {}
    for name in ("semantic_inventory", "delivery_ir", "input_gate", "verify", "html_writer", "pptx_writer", "__init__"):
        relative = "client_delivery/" + name + ".py"
        path = ENGINE_ROOT / relative
        raw = read_regular(path)
        require(digest(raw) == SOURCE_HASHES[relative], "BOUND_ENGINE_SOURCE_DRIFT:" + relative)
        if name == "__init__":
            module = package
        else:
            module = types.ModuleType(namespace + "." + name)
            module.__package__ = namespace
            module.__file__ = str(path)
            sys.modules[module.__name__] = module
            setattr(package, name, module)
        exec(compile(raw, str(path), "exec"), module.__dict__)
        loaded[name] = module
    return tuple(loaded[name] for name in ("pptx_writer", "html_writer", "verify", "semantic_inventory"))


def html_checks(path: Path, ir: dict, profile: str, modules: tuple) -> None:
    _, writer, verifier, semantic = modules
    text = read_regular(path).decode("utf-8")
    lower = text.lower()
    expected_root = '<html lang="zh-CN">' if profile == "control" else f'<html class="timeline-profile-{profile}" lang="zh-CN">'
    require(text.count(expected_root) == 1, "HTML_PROFILE_DRIFT")
    require(not any(t in lower for t in ("<script", "<link", "http://", "https://", "file://", "javascript:", "@import", "@font-face", "url(", "cdn")), "HTML_OFFLINE_CLOSURE_FAILED")
    require(re.search(r"\b(?:src|href)\s*=", lower) is None, "HTML_FETCH_ATTRIBUTE")
    css = writer._CSS if profile == "control" else writer._CSS + "\n" + writer._TIMELINE_PROFILE_CSS
    require(re.findall(r"<style>(.*?)</style>", text, re.S) == [css], "HTML_CSS_DRIFT")
    require(text.count(f'<ol class="timeline {PROFILES[profile]}">') == 1, "HTML_COMPOSITION_DRIFT")
    require(lower.count('<article class="slide role-') == 13, "HTML_PAGE_COUNT_DRIFT")
    verifier._verify_html_visible_text_ledger(text, 13, ir)
    semantic.compare_rendered_inventory(ir, re.findall(r'\bdata-semantic-id="(sem:[A-Za-z0-9._:-]+)"', text), artifact_format="html")


def six_checks(directory: Path, ir: dict, modules: tuple) -> list[dict]:
    _, _, verifier, _ = modules
    reports = []
    for profile in PROFILES:
        for extension in ("pptx", "html"):
            filename = f"timeline-profile-{profile}.REVIEW-DRAFT.{extension}"
            path = directory / filename
            raw = read_regular(path)
            require(digest(raw) == ARTIFACT_HASHES[filename], "APPROVED_ARTIFACT_HASH_MISMATCH:" + filename)
            if extension == "pptx":
                verifier.verify_pptx(path, ir, timeline_profile=None if profile == "control" else profile)
                with zipfile.ZipFile(path) as archive:
                    require(not any(n.lower().startswith("ppt/media/") for n in archive.namelist()), "PPTX_MEDIA_FORBIDDEN")
                    for name in archive.namelist():
                        if re.fullmatch(r"ppt/slides/slide\d+\.xml", name):
                            require(not ET.fromstring(archive.read(name)).findall(".//p:pic", NS), "PPTX_FLATTENING_FORBIDDEN")
            else:
                html_checks(path, ir, profile, modules)
            reports.append({"file": filename, "profile": profile, "format": extension, "sha256": "sha256:" + digest(raw), "size_bytes": len(raw), "page_count": 13, "semantic_item_count": 47})
    return reports


def checked_drawio(directory: Path) -> dict:
    from .drawio_export import build, FILENAME
    xml, ledger = build(directory)
    require(digest(xml) == ARTIFACT_HASHES[FILENAME], "APPROVED_DRAWIO_HASH_MISMATCH")
    require(read_regular(directory / FILENAME) == xml, "DRAWIO_SOURCE_OR_OUTPUT_DRIFT")
    require(read_regular(directory / MAP_OUTPUT) == canonical(ledger), "DRAWIO_MAP_DRIFT")
    root = ET.fromstring(xml)
    require([d.get("id") for d in root.findall("diagram")] == ["r2-" + p for p in PROFILES], "DRAWIO_PROFILE_ORDER")
    require(len(root.findall(".//object")) == 51, "DRAWIO_NATIVE_OBJECT_COUNT")
    for obj in root.findall(".//object"):
        cell = obj.find("mxCell")
        require(cell is not None and cell.get("vertex") == "1" and "editable=1;" in cell.get("style", ""), "DRAWIO_NOT_NATIVE_EDITABLE")
    return {"file": FILENAME, "format": "drawio", "sha256": "sha256:" + digest(xml), "size_bytes": len(xml), "page_count": 3, "native_object_count": 51, "scope": "fixed timeline slide 6 only, one page per profile", "renderer_qa_performed": False}


def expected_receipt(artifacts: list[dict]) -> dict:
    return {
        "schema": "fixed-synthetic-timeline-demo/1.0",
        "status": "PASS_FIXED_SYNTHETIC_DEMO_ONLY",
        "data_class": "synthetic", "release_state": "REVIEW_DRAFT",
        "fixed_ir_sha256": "sha256:" + IR_SHA256,
        "bound_engine_sources": SOURCE_HASHES, "bound_sources_unchanged": True,
        "runtime_versions": RUNTIME, "double_build_byte_identical": True,
        "requested_profiles": list(PROFILES), "produced_profiles": list(PROFILES),
        "artifact_count": 7, "artifacts": artifacts,
        "geometry_qa_replayed": False, "drawio_renderer_qa_replayed": False,
        "assurance": "Exact approved artifact bytes plus live native, semantic and offline structural checks; not fresh renderer QA.",
        "scope": "Frozen public synthetic three-event sample only; no general A/B writer or generic draw.io export claim.",
        "holds": ["NO_REAL_CASE_INPUT", "NO_FORMAL_PROMOTION", "NO_CLIENT_COURT_OR_PUBLIC_RELEASE", "NO_LEGAL_OR_FACT_COMPLETENESS_CLAIM"],
    }


def verify_demo(directory: Path) -> dict:
    """Read-only verification of a complete demo; edits intentionally fail binding."""
    bound_sources()
    ir, raw = fixed_ir()
    require(read_regular(directory / IR_OUTPUT) == raw, "OUTPUT_IR_DRIFT")
    modules = engine_modules()
    artifacts = six_checks(directory, ir, modules) + [checked_drawio(directory)]
    expected = expected_receipt(artifacts)
    require(read_regular(directory / RECEIPT) == canonical(expected), "DEMO_RECEIPT_DRIFT")
    files = set()
    for path in directory.rglob("*"):
        require(not path.is_symlink(), "OUTPUT_SYMLINK")
        if path.is_file():
            files.add(path.relative_to(directory).as_posix())
    require(files == set(ARTIFACT_HASHES) | {IR_OUTPUT, MAP_OUTPUT, RECEIPT}, "OUTPUT_FILE_SET_DRIFT")
    return expected


def render_stage(stage: Path, transient: Path, ir: dict, raw: bytes, modules: tuple) -> None:
    from .drawio_export import build, FILENAME
    pptx, html, verifier, _ = modules
    stage.mkdir(exist_ok=True)
    require(not any(stage.iterdir()), "STAGE_MUST_BE_EMPTY")
    (stage / "internal-audit").mkdir()
    (stage / IR_OUTPUT).write_bytes(raw)
    for profile in PROFILES:
        value = None if profile == "control" else profile
        path = stage / f"timeline-profile-{profile}.REVIEW-DRAFT.pptx"
        pptx.write_presentation(stage / IR_OUTPUT, path, transient / profile, timeline_profile=value)
        verifier.normalize_pptx(path)
        html.render_html(ir, stage / f"timeline-profile-{profile}.REVIEW-DRAFT.html", timeline_profile=value)
    artifacts = six_checks(stage, ir, modules)
    xml, ledger = build(stage)
    require(digest(xml) == ARTIFACT_HASHES[FILENAME], "APPROVED_DRAWIO_HASH_MISMATCH")
    (stage / FILENAME).write_bytes(xml)
    (stage / MAP_OUTPUT).write_bytes(canonical(ledger))
    artifacts.append(checked_drawio(stage))
    (stage / RECEIPT).write_bytes(canonical(expected_receipt(artifacts)))
    verify_demo(stage)


def inventory(directory: Path) -> dict[str, str]:
    return {p.relative_to(directory).as_posix(): digest(read_regular(p)) for p in directory.rglob("*") if p.is_file() or p.is_symlink()}


def checked_output(path: Path) -> Path:
    path = path.absolute()
    require(path.name not in {"", ".", ".."}, "INVALID_OUTPUT")
    for item in (path, *path.parents):
        require(not item.is_symlink(), "OUTPUT_SYMLINK_ANCESTOR")
    require(not path.exists(), "OUTPUT_ALREADY_EXISTS")
    require(path.parent.is_dir(), "OUTPUT_PARENT_MUST_EXIST")
    resolved = path.resolve()
    for protected in (PACKAGE_ROOT.resolve(), ENGINE_ROOT.resolve(), FIXTURE.parent.resolve()):
        require(resolved != protected and protected not in resolved.parents, "OUTPUT_INSIDE_SOURCE_PACKAGE")
    return resolved


def rename_new(source: Path, target: Path) -> None:
    """Atomic no-replace commit; unsupported host/filesystem fails closed."""
    if os.name == "nt":
        os.rename(source, target)  # Windows rename refuses an existing target.
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        function = libc.renamex_np
        function.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        function.restype = ctypes.c_int
        result = function(os.fsencode(source), os.fsencode(target), 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        function = libc.renameat2
        function.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        function.restype = ctypes.c_int
        result = function(-100, os.fsencode(source), -100, os.fsencode(target), 1)  # AT_FDCWD, RENAME_NOREPLACE
    else:
        raise DemoError("ATOMIC_NOREPLACE_UNAVAILABLE")
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, "ATOMIC_NOREPLACE_COMMIT_FAILED")


def run_demo(out: Path) -> dict:
    """Commit all seven artifacts only after two complete, identical staged builds."""
    output = checked_output(out)
    before = bound_sources()
    runtime_check()
    ir, raw = fixed_ir()
    modules = engine_modules()
    ready: Path | None = Path(tempfile.mkdtemp(prefix=".timeline-demo-ready-", dir=output.parent))
    try:
        with tempfile.TemporaryDirectory(prefix=".timeline-demo-stage-", dir=output.parent) as temporary:
            work = Path(temporary)
            second = work / "second"
            render_stage(ready, work / "qa-first", ir, raw, modules)
            render_stage(second, work / "qa-second", ir, raw, modules)
            require(inventory(ready) == inventory(second), "NONDETERMINISTIC_DEMO")
            receipt = verify_demo(ready)
        # All fallible temporary-work cleanup is completed before publication.
        require(bound_sources() == before, "BOUND_SOURCE_CHANGED_DURING_RUN")
        require(not output.exists() and not output.is_symlink(), "OUTPUT_CREATED_DURING_RUN")
        # The output parent must be operator-controlled. Native no-replace
        # semantics also protect a target created between the check and commit.
        rename_new(ready, output)
        ready = None
        return receipt
    finally:
        if ready is not None:
            shutil.rmtree(ready)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate only the frozen, synthetic three-event Control/A/B demo; not a real-case input interface.")
    parser.add_argument("--out", required=True, type=Path, help="fresh output directory outside this package; parent must already exist")
    args = parser.parse_args(argv)
    try:
        result = run_demo(args.out)
    except Exception as exc:
        print("HOLD_TIMELINE_DEMO:" + type(exc).__name__ + ":" + str(exc), file=sys.stderr)
        return 3
    print(json.dumps({"status": result["status"], "artifact_count": result["artifact_count"], "release_state": result["release_state"]}, sort_keys=True))
    return 0
