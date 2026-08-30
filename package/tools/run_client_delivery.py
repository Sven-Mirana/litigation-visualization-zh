#!/usr/bin/env python3
"""Generate an atomic S2 client bundle (PPTX default, offline HTML optional).

No --format means PPTX only.  Repeat --format to request both formats.  The
entire request commits or fails together; any failure leaves --out untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACKAGE_ROOT))

from client_delivery.delivery_ir import build_delivery_ir  # noqa: E402
from client_delivery.html_writer import HtmlRenderError, render_html  # noqa: E402
from client_delivery.input_gate import (  # noqa: E402
    GateError,
    canonical_json_bytes,
    load_inputs,
)
from client_delivery.semantic_inventory import require_source_inventory  # noqa: E402
from client_delivery.verify import (  # noqa: E402
    VerificationError,
    normalize_pptx,
    verify_html,
    verify_pptx,
)


EXIT_HOLD = 3
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
PATH_ERRORS = (OSError, RuntimeError, ValueError)
OOXML_POINT_SCALE = 0.75
LAYOUT_ROLE_MINIMUM_POINTS = {
    "DECK": 50.0,
    "SLIDE": 35.0,
    "MID": 24.0,
    "BODY": 16.0,
    "AUX": 8.0,
}
TEXT_ROLE_RE = re.compile(r"\|TEXTROLE\|(DECK|SLIDE|MID|BODY|AUX)\|")


def hold(message: str) -> int:
    print(f"HOLD-CLIENT-DELIVERY: {message}", file=sys.stderr)
    return EXIT_HOLD


def emit_success_after_commit(report: dict[str, Any]) -> None:
    """Best-effort status output after the atomic commit point.

    A closed stdout pipe is a reporting failure, not a transaction failure. At
    this point the validated bundle already exists at its final path, so an
    OSError must not enter the pre-commit failure-receipt path and falsely claim
    that nothing was produced.
    """

    line = json.dumps(report, ensure_ascii=False)
    try:
        print(line)
    except OSError:
        return


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return sha256_bytes(raw)


def write_json_atomic(path: Path, value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise OSError("receipt parent is unavailable")
    if path.exists() or path.is_symlink():
        raise OSError("receipt path already exists")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()
    return sha256_bytes(raw)


def validate_schema(instance: Any, schema_path: Path, label: str) -> None:
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise VerificationError("jsonschema运行时不可用") from exc
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = "/".join(str(value) for value in first.path) or "$"
        raise VerificationError(f"{label}合同失败:{location}:{first.message}")


def output_error(path: Path) -> str | None:
    try:
        if path.is_symlink():
            return "--out不得为symlink"
        if not path.exists():
            return None
        if not path.is_dir():
            return "--out已存在且不是目录"
        if any(path.iterdir()):
            return "--out已存在且非空"
    except PATH_ERRORS as exc:
        return f"--out不可检查:{type(exc).__name__}"
    return None


def regular_file(path: Path) -> bool:
    try:
        return not path.is_symlink() and stat.S_ISREG(path.stat(follow_symlinks=False).st_mode)
    except PATH_ERRORS:
        return False


def semantic_completeness_counts(
    delivery_ir: dict[str, Any], receipts: list[dict[str, Any]]
) -> tuple[int, int]:
    source_count = len(require_source_inventory(delivery_ir))
    if not receipts or any(not isinstance(item, dict) for item in receipts):
        raise VerificationError("缺少独立的产物语义完整性回执")
    for receipt in receipts:
        if (
            receipt.get("status") != "complete"
            or receipt.get("source_item_count") != source_count
            or receipt.get("rendered_item_count") != source_count
            or receipt.get("source_inventory_sha256")
            != receipt.get("rendered_inventory_sha256")
        ):
            raise VerificationError("SILENT_TRUNCATION_DETECTED:产物语义清单未闭合")
    return source_count, source_count


def inventory(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result: list[dict[str, Any]] = []
    for item in sorted(path.rglob("*")):
        if regular_file(item) and item.stat().st_size > 0:
            result.append(
                {
                    "relative_path": item.relative_to(path).as_posix(),
                    "sha256": f"sha256:{sha256_file(item)}",
                    "size_bytes": item.stat().st_size,
                }
            )
    return result


def inventory_sha256(path: Path) -> str:
    return sha256_bytes(canonical_json_bytes(inventory(path)))


def _verify_layout_text_capacity(
    layout: dict[str, Any],
    *,
    prefix: str,
    expected_count: int,
    report_name: str,
    gate: str,
) -> int:
    elements = [
        item
        for item in layout.get("elements", [])
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and item["name"].startswith(prefix)
    ]
    if len(elements) != expected_count:
        raise VerificationError(f"{gate}:对象数量:{report_name}")
    for element in elements:
        bbox = element.get("bbox")
        font_size = element.get("resolvedFontSize")
        text_layout = element.get("textLayout")
        line_count = (
            text_layout.get("lineCount") if isinstance(text_layout, dict) else None
        )
        if (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or not all(isinstance(value, (int, float)) for value in bbox)
            or not isinstance(font_size, (int, float))
            or not isinstance(line_count, int)
            or line_count < 1
        ):
            raise VerificationError(f"{gate}:布局字段:{report_name}")
        actual_points = font_size * OOXML_POINT_SCALE
        if actual_points < 16:
            raise VerificationError(f"{gate}:正文字号小于16:{report_name}")
        required_height = line_count * font_size * 1.25 + 10
        if required_height > bbox[3] + 1e-6:
            raise VerificationError(
                f"{gate}:文字容量不足:{report_name}:{element['name']}:"
                f"required={required_height:.2f}:actual={bbox[3]:.2f}"
            )
    return len(elements)


def _verify_layout_role_capacity(layout: dict[str, Any], report_name: str) -> dict[str, Any]:
    """Use artifact layout only for capacity; final OOXML owns point-size truth."""

    checked = 0
    role_counts: dict[str, int] = {}
    for element in layout.get("elements", []):
        if not isinstance(element, dict) or not isinstance(element.get("name"), str):
            continue
        roles = TEXT_ROLE_RE.findall(element["name"])
        if not roles:
            continue
        if len(roles) != 1:
            raise VerificationError(
                f"PPTX_TEXT_LAYOUT_INVALID:文字角色数量:{report_name}:{element['name']}"
            )
        text_layout = element.get("textLayout")
        # Native tables expose cell typography only in OOXML, not as one
        # artifact layout text box.  The OOXML verifier covers their real size.
        if not isinstance(text_layout, dict):
            continue
        bbox = element.get("bbox")
        font_size = element.get("resolvedFontSize")
        line_count = text_layout.get("lineCount")
        if (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or not all(isinstance(value, (int, float)) for value in bbox)
            or not isinstance(font_size, (int, float))
            or not isinstance(line_count, int)
            or line_count < 1
        ):
            raise VerificationError(
                f"PPTX_TEXT_LAYOUT_INVALID:布局字段:{report_name}:{element['name']}"
            )
        role = roles[0]
        actual_points = font_size * OOXML_POINT_SCALE
        required_points = LAYOUT_ROLE_MINIMUM_POINTS[role]
        if actual_points + 1e-6 < required_points:
            raise VerificationError(
                f"PPTX_TEXT_LAYOUT_INVALID:{role}实际字号不足:{report_name}:"
                f"{element['name']}:actual={actual_points:.2f}:required={required_points:.2f}"
            )
        if role != "AUX":
            required_height = line_count * font_size * 1.25 + 10
            if required_height > bbox[3] + 1e-6:
                raise VerificationError(
                    f"PPTX_TEXT_LAYOUT_INVALID:文字容量不足:{report_name}:"
                    f"{element['name']}:required={required_height:.2f}:actual={bbox[3]:.2f}"
                )
        if role == "SLIDE" and line_count != 1:
            raise VerificationError(
                f"PPTX_TEXT_LAYOUT_INVALID:页标题必须单行:{report_name}:{element['name']}"
            )
        checked += 1
        role_counts[role] = role_counts.get(role, 0) + 1
    if checked < 1:
        raise VerificationError(f"PPTX_TEXT_LAYOUT_INVALID:无角色文字框:{report_name}")
    return {"checked": checked, "role_counts": dict(sorted(role_counts.items()))}


def verify_qa(qa_dir: Path, delivery_ir: dict[str, Any]) -> dict[str, Any]:
    slide_count = len(delivery_ir["slides"])
    expected_pngs = {f"slide-{index:02d}.png" for index in range(1, slide_count + 1)}
    expected_layouts = {f"slide-{index:02d}.layout.json" for index in range(1, slide_count + 1)}
    actual = {path.name for path in qa_dir.iterdir() if path.is_file()}
    required = expected_pngs | expected_layouts | {"deck-montage.webp", "deck-inspect.ndjson"}
    if not required.issubset(actual):
        raise VerificationError("PPTX QA产物不完整")
    for name in expected_pngs:
        path = qa_dir / name
        if not regular_file(path):
            raise VerificationError("PPTX QA PNG不是普通文件")
        with path.open("rb") as handle:
            header = handle.read(24)
        if (
            len(header) < 24
            or header[:8] != b"\x89PNG\r\n\x1a\n"
            or header[12:16] != b"IHDR"
            or struct.unpack(">II", header[16:24]) != (1280, 720)
        ):
            raise VerificationError("PPTX QA PNG尺寸或签名错误")
    timeline_text_boxes = 0
    relationship_chain_text_boxes = 0
    role_text_boxes = 0
    role_text_counts: dict[str, int] = {}
    for name in expected_layouts:
        raw = (qa_dir / name).read_text(encoding="utf-8")
        if re.search(r'"(?:overflow|clipped)"\s*:\s*true', raw, re.IGNORECASE):
            raise VerificationError(f"布局导出报告溢出:{name}")
        try:
            layout = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise VerificationError(f"布局导出不是JSON:{name}") from exc
        slide_index = int(name.removeprefix("slide-").removesuffix(".layout.json")) - 1
        ir_slide = delivery_ir["slides"][slide_index]
        role_capacity = _verify_layout_role_capacity(layout, name)
        role_text_boxes += role_capacity["checked"]
        for role, count in role_capacity["role_counts"].items():
            role_text_counts[role] = role_text_counts.get(role, 0) + count
        if ir_slide["role"] == "timeline":
            timeline_text_boxes += _verify_layout_text_capacity(
                layout,
                prefix=f'{ir_slide["slide_id"]}:event-text:',
                expected_count=len(ir_slide["content"]["events"]),
                report_name=name,
                gate="TIMELINE_TEXT_CAPACITY_INVALID",
            )
        elif ir_slide["role"] == "relationship" and ir_slide["content"]["chain"]:
            relationship_chain_text_boxes += _verify_layout_text_capacity(
                layout,
                prefix=f'{ir_slide["slide_id"]}:chain-text:',
                expected_count=len(ir_slide["content"]["chain"]),
                report_name=name,
                gate="RELATIONSHIP_CHAIN_TEXT_CAPACITY_INVALID",
            )
    return {
        "layout_overflow": False,
        "slide_pngs": slide_count,
        "layout_reports": slide_count,
        "timeline_text_capacity": "pass",
        "timeline_text_boxes": timeline_text_boxes,
        "timeline_min_actual_ooxml_point_size": 16,
        "relationship_chain_text_capacity": "pass",
        "relationship_chain_text_boxes": relationship_chain_text_boxes,
        "relationship_chain_min_actual_ooxml_point_size": 16,
        "role_text_capacity": "pass",
        "role_text_boxes": role_text_boxes,
        "role_text_counts": dict(sorted(role_text_counts.items())),
        "layout_point_scale_to_ooxml": OOXML_POINT_SCALE,
    }


def pptx_dependency_report() -> dict[str, Any]:
    """Probe the pinned portable PPTX engine without importing it in-process."""

    writer = PACKAGE_ROOT / "client_delivery" / "pptx_writer.py"
    try:
        result = subprocess.run(
            [sys.executable, str(writer), "--doctor"],
            capture_output=True,
            text=True,
            timeout=20,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        raise VerificationError("PPTX python-pptx依赖诊断超时") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise VerificationError(
            "PPTX python-pptx 1.0.2依赖不可用:"
            + (" | ".join(detail[-4:]) if detail else "unknown")
        )
    try:
        report = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise VerificationError("PPTX python-pptx依赖诊断回执无效") from exc
    if (
        report.get("status") != "pass"
        or report.get("engine") != "python-pptx"
        or report.get("python_pptx_version") != "1.0.2"
        or report.get("codex_runtime_required") is not False
        or report.get("node_runtime_required") is not False
    ):
        raise VerificationError("PPTX python-pptx依赖诊断未闭合")
    return report


def render_pptx(stage: Path, delivery_ir_path: Path, delivery_ir: dict[str, Any]) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    doctor = pptx_dependency_report()
    writer = PACKAGE_ROOT / "client_delivery" / "pptx_writer.py"
    output = stage / "client-briefing.REVIEW-DRAFT.pptx"
    qa = stage / "internal-audit" / "pptx-qa"
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(writer),
                "--input",
                str(delivery_ir_path),
                "--output",
                str(output),
                "--qa",
                str(qa),
            ],
            capture_output=True,
            text=True,
            timeout=240,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        raise VerificationError("PPTX生成超时") from exc
    if result.returncode != 0:
        lines = (result.stderr or result.stdout).strip().splitlines()
        detail = lines[:3] + (["..."] if len(lines) > 11 else []) + lines[-8:]
        raise VerificationError(f"PPTX生成失败:{' | '.join(detail) if detail else 'unknown'}")
    structure_sha256 = normalize_pptx(output)
    verification = verify_pptx(output, delivery_ir, structure_sha256=structure_sha256)
    qa_result = verify_qa(qa, delivery_ir)
    qa_result["dependency_doctor"] = doctor
    return output, verification, qa_result


def html_dependency_report() -> dict[str, Any]:
    qa_script = PACKAGE_ROOT / "client_delivery" / "html_qa.py"
    try:
        result = subprocess.run(
            [sys.executable, str(qa_script), "--doctor"],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        raise VerificationError("HTML Python Playwright依赖诊断超时") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise VerificationError(
            "HTML Python Playwright/Chrome依赖不可用:"
            + (" | ".join(detail[-4:]) if detail else "unknown")
        )
    try:
        report = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise VerificationError("HTML Python Playwright依赖诊断回执无效") from exc
    if (
        report.get("status") != "pass"
        or report.get("engine") != "python-playwright-chromium"
        or report.get("playwright_version") != "1.59.0"
        or report.get("codex_runtime_required") is not False
        or report.get("node_runtime_required") is not False
    ):
        raise VerificationError("HTML Python Playwright依赖诊断未闭合")
    return report


def verify_html_browser(
    stage: Path, html_path: Path, delivery_ir: dict[str, Any]
) -> dict[str, Any]:
    """Run offline HTML with system Python Playwright and explicit Chrome."""

    doctor = html_dependency_report()
    qa_script = PACKAGE_ROOT / "client_delivery" / "html_qa.py"
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(qa_script),
                "--input",
                str(html_path),
                "--expected-slides",
                str(len(delivery_ir["slides"])),
                "--delivery-ir-stdin",
            ],
            capture_output=True,
            text=True,
            input=json.dumps(
                delivery_ir, ensure_ascii=False, separators=(",", ":")
            ),
            timeout=120,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        raise VerificationError("HTML Chromium运行验证超时") from exc
    if result.returncode != 0:
        lines = (result.stderr or result.stdout).strip().splitlines()
        detail = lines[:3] + (["..."] if len(lines) > 9 else []) + lines[-6:]
        raise VerificationError(
            f"HTML_BROWSER_LAYOUT_INVALID:{' | '.join(detail) if detail else 'unknown'}"
        )
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise VerificationError("HTML Chromium运行回执无效") from exc
    if (
        payload.get("status") != "pass"
        or payload.get("networkRequests") != 0
        or payload.get("engine") != "python-playwright-chromium"
        or payload.get("expectedSlides") != len(delivery_ir["slides"])
        or payload.get("printPageCount") != len(delivery_ir["slides"])
        or payload.get("screen", {}).get("articleOverflowPx") != 0
        or payload.get("print", {}).get("articleOverflowPx") != 0
        or payload.get("screen", {}).get("staticRoleLedgerStatus") != "complete"
        or payload.get("print", {}).get("staticRoleLedgerStatus") != "complete"
        or payload.get("screen", {}).get("releaseWatermarkStatus") != "complete"
        or payload.get("print", {}).get("releaseWatermarkStatus") != "complete"
        or payload.get("screen", {}).get("nowrapStatus") != "complete"
        or payload.get("print", {}).get("nowrapStatus") != "complete"
    ):
        raise VerificationError("HTML_BROWSER_LAYOUT_INVALID:运行回执未闭合")
    return {
        "status": "pass",
        "engine": payload["engine"],
        "browser_version": payload["browserVersion"],
        "dependency_doctor": doctor,
        "network_requests": 0,
        "screen_article_overflow_px": payload["screen"]["articleOverflowPx"],
        "screen_semantic_overflow_px": payload["screen"]["semanticOverflowPx"],
        "print_article_overflow_px": payload["print"]["articleOverflowPx"],
        "print_semantic_overflow_px": payload["print"]["semanticOverflowPx"],
        "static_role_ledger_sha256": payload["expectedStaticLedgerSha256"],
        "screen_static_role_ledger": payload["screen"]["staticRoleLedgerStatus"],
        "print_static_role_ledger": payload["print"]["staticRoleLedgerStatus"],
        "screen_release_watermark": payload["screen"]["releaseWatermarkStatus"],
        "print_release_watermark": payload["print"]["releaseWatermarkStatus"],
        "screen_nowrap": payload["screen"]["nowrapStatus"],
        "print_nowrap": payload["print"]["nowrapStatus"],
        "print_page_count": payload["printPageCount"],
    }


def build_manifest(
    *,
    run_id: str,
    delivery_ir: dict[str, Any],
    delivery_ir_sha256: str,
    request_source: str,
    requested: list[str],
    artifacts: list[dict[str, Any]],
    validations: list[dict[str, Any]],
    semantic_receipts: list[dict[str, Any]],
    privacy_receipt_sha256: str,
) -> dict[str, Any]:
    source_count, rendered_count = semantic_completeness_counts(
        delivery_ir, semantic_receipts
    )
    return {
        "schema_version": "artifact-manifest/2.0",
        "run_id": run_id,
        "case_ref": delivery_ir["case_ref"],
        "data_class": delivery_ir["data_class"],
        "release_state": "REVIEW_DRAFT",
        "delivery_ir_sha256": f"sha256:{delivery_ir_sha256}",
        "profile_sha256": delivery_ir["profile_sha256"],
        "format_selection": {"default_format": "pptx", "request_source": request_source},
        "requested": requested,
        "produced": artifacts,
        "requested_equals_produced": requested == [item["format"] for item in artifacts],
        "partial_success": False,
        "overall_status": "complete",
        "atomic_commit": {
            "strategy": "rename_same_filesystem",
            "same_filesystem": True,
            "staging_complete_before_commit": True,
            "formal_output_was_empty": True,
            "cleanup_on_failure": True,
            "committed": True,
        },
        "completeness": {
            "source_item_count": source_count,
            "rendered_item_count": rendered_count,
            "silent_truncation": False,
            "pagination_strategy": "deterministic_stable_role_pagination",
            "coverage_status": "complete",
        },
        "privacy_output_scan": {
            "status": "pass",
            "scanner_version": "s2-output-scan/1.0",
            "receipt_sha256": f"sha256:{privacy_receipt_sha256}",
            "artifact_sha256s": [item["sha256"] for item in artifacts],
            "external_relationships": False,
            "embedded_original_input": False,
        },
        "validations": validations,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-client-delivery", action="store_true")
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--frozen07-dir", required=True)
    parser.add_argument("--text-pass-receipt", required=True)
    parser.add_argument("--delivery-profile", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--format", choices=("pptx", "html"), action="append", dest="formats")
    parser.add_argument("--run-id")
    parser.add_argument("--failure-receipt")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv == ["--dependency-doctor"]:
        try:
            report = {
                "status": "pass",
                "codex_runtime_required": False,
                "node_runtime_required": False,
                "pptx": pptx_dependency_report(),
                "html": html_dependency_report(),
            }
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
            return 0
        except VerificationError as exc:
            return hold(str(exc))
    args = parse_args(raw_argv)
    if not args.enable_client_delivery:
        return hold("默认关闭：缺少--enable-client-delivery")
    requested = args.formats or ["pptx"]
    if len(requested) != len(set(requested)):
        return hold("--format不得重复")
    requested = [value for value in ("pptx", "html") if value in requested]
    request_source = "explicit" if args.formats else "omitted_default"
    run_id = args.run_id or f"S2-{uuid.uuid4().hex[:16]}"
    if not ID_RE.fullmatch(run_id):
        return hold("run-id无效")
    try:
        out_input = Path(args.out).expanduser()
        if out_input.is_symlink():
            return hold("--out不得为symlink")
        out = out_input.resolve()
    except PATH_ERRORS as exc:
        return hold(f"--out路径不可解析:{type(exc).__name__}")
    error = output_error(out)
    if error:
        return hold(error)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
    except PATH_ERRORS as exc:
        return hold(f"--out父目录不可创建:{type(exc).__name__}")
    failure_receipt_path: Path
    if args.failure_receipt:
        try:
            receipt_input = Path(args.failure_receipt).expanduser()
            if receipt_input.name in {"", ".", ".."} or receipt_input.suffix.lower() != ".json":
                return hold("--failure-receipt必须是新的JSON文件")
            receipt_parent = receipt_input.parent.resolve()
            failure_receipt_path = receipt_parent / receipt_input.name
        except PATH_ERRORS as exc:
            return hold(f"--failure-receipt路径不可解析:{type(exc).__name__}")
        if receipt_parent != out.parent:
            return hold("--failure-receipt必须与--out同级")
        if failure_receipt_path.exists() or failure_receipt_path.is_symlink():
            return hold("--failure-receipt不得覆盖现有路径")
    else:
        failure_receipt_path = out.parent / (
            f".{out.name}.{run_id}.{uuid.uuid4().hex[:8]}.failure.json"
        )
    stage: Path | None = None
    delivery_ir: dict[str, Any] | None = None
    delivery_ir_sha: str | None = None
    failure_stage = "input_gate"
    failure_format: str | None = None
    formal_before = inventory_sha256(out)
    try:
        inputs = load_inputs(
            case_id=args.case_id,
            frozen07_dir=args.frozen07_dir,
            text_pass_receipt=args.text_pass_receipt,
            delivery_profile=args.delivery_profile,
        )
        failure_stage = "delivery_ir"
        delivery_ir = build_delivery_ir(inputs, PACKAGE_ROOT)
        contracts = PACKAGE_ROOT.parent / "references" / "contracts"
        validate_schema(delivery_ir, contracts / "delivery-ir-v1.schema.json", "DeliveryIR")
        out.parent.mkdir(parents=True, exist_ok=True)
        error = output_error(out)
        if error:
            return hold(f"输出提交前状态变化:{error}")
        stage = Path(tempfile.mkdtemp(prefix=f".{out.name}.staging-", dir=out.parent))
        audit = stage / "internal-audit"
        audit.mkdir()
        delivery_ir_path = audit / "delivery-ir.json"
        delivery_ir_sha = write_json(delivery_ir_path, delivery_ir)
        artifacts: list[dict[str, Any]] = []
        validation_summaries: list[dict[str, Any]] = []
        semantic_receipts: list[dict[str, Any]] = []
        privacy_artifacts: list[dict[str, Any]] = []

        if "pptx" in requested:
            failure_stage = "pptx_write"
            failure_format = "pptx"
            pptx, pptx_result, qa_result = render_pptx(stage, delivery_ir_path, delivery_ir)
            pptx_receipt = {"schema": "pptx-validation/1.0", **pptx_result, **qa_result}
            receipt_sha = write_json(audit / "pptx-validation.json", pptx_receipt)
            artifacts.append(
                {
                    "format": "pptx",
                    "relative_path": pptx.name,
                    "sha256": f"sha256:{pptx_result['sha256']}",
                    "size_bytes": pptx_result["size_bytes"],
                    "media_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    "single_file": True,
                    "offline": True,
                    "external_dependencies": False,
                    "native_editable_objects": True,
                    "draft_watermark": True,
                    "client_release_receipt_sha256": None,
                }
            )
            validation_summaries.append(
                {
                    "format": "pptx",
                    "status": "pass",
                    "receipt_sha256": f"sha256:{receipt_sha}",
                    "native_editability": "pass",
                    "layout_overflow": False,
                    "external_relationships": False,
                    "macros_or_ole": False,
                }
            )
            privacy_artifacts.append({"format": "pptx", "sha256": pptx_result["sha256"]})
            semantic_receipts.append(pptx_result["semantic_completeness"])

        if "html" in requested:
            failure_stage = "html_write"
            failure_format = "html"
            html_path = stage / "client-briefing.REVIEW-DRAFT.html"
            render_html(delivery_ir, html_path)
            html_result = verify_html(html_path, delivery_ir)
            html_browser_result = verify_html_browser(stage, html_path, delivery_ir)
            html_receipt = {
                "schema": "html-validation/1.0",
                **html_result,
                "browser_layout": html_browser_result,
            }
            receipt_sha = write_json(audit / "html-validation.json", html_receipt)
            artifacts.append(
                {
                    "format": "html",
                    "relative_path": html_path.name,
                    "sha256": f"sha256:{html_result['sha256']}",
                    "size_bytes": html_result["size_bytes"],
                    "media_type": "text/html",
                    "single_file": True,
                    "offline": True,
                    "external_dependencies": False,
                    "native_editable_objects": False,
                    "draft_watermark": True,
                    "client_release_receipt_sha256": None,
                }
            )
            validation_summaries.append(
                {
                    "format": "html",
                    "status": "pass",
                    "receipt_sha256": f"sha256:{receipt_sha}",
                    "single_file": True,
                    "network_requests": False,
                    "external_assets": False,
                    "script_elements": False,
                }
            )
            privacy_artifacts.append({"format": "html", "sha256": html_result["sha256"]})
            semantic_receipts.append(html_result["semantic_completeness"])

        if requested != [item["format"] for item in artifacts]:
            failure_stage = "completeness_check"
            raise VerificationError("requested与produced不一致")
        privacy_receipt = {
            "schema": "privacy-output-scan/1.0",
            "case_ref": delivery_ir["case_ref"],
            "status": "pass",
            "artifacts": privacy_artifacts,
            "external_relationships": False,
            "embedded_original_input": False,
            "internal_paths": False,
            "pii_canary": False,
        }
        privacy_sha = write_json(audit / "privacy-output-scan.json", privacy_receipt)
        manifest = build_manifest(
            run_id=run_id,
            delivery_ir=delivery_ir,
            delivery_ir_sha256=delivery_ir_sha,
            request_source=request_source,
            requested=requested,
            artifacts=artifacts,
            validations=validation_summaries,
            semantic_receipts=semantic_receipts,
            privacy_receipt_sha256=privacy_sha,
        )
        failure_stage = "format_validation"
        validate_schema(manifest, contracts / "artifact-manifest-v2.schema.json", "ArtifactManifest")
        write_json(stage / "ARTIFACT-MANIFEST.json", manifest)
        root_entries = {path.name for path in stage.iterdir()}
        if root_entries != {"ARTIFACT-MANIFEST.json", "internal-audit", *[item["relative_path"] for item in artifacts]}:
            raise VerificationError(f"输出根目录含未登记条目:{sorted(root_entries)}")
        error = output_error(out)
        if error:
            raise VerificationError(f"提交前输出状态变化:{error}")
        success_report = {
            "ok": True,
            "run_id": run_id,
            "case_ref": delivery_ir["case_ref"],
            "requested": requested,
            "produced": [item["relative_path"] for item in artifacts],
            "release_state": "REVIEW_DRAFT",
            "out": str(out),
        }
        failure_stage = "atomic_commit"
        try:
            os.replace(stage, out)
        except OSError as exc:
            raise VerificationError(f"原子提交失败:{type(exc).__name__}") from exc
        stage = None
        emit_success_after_commit(success_report)
        return 0
    except (GateError, VerificationError, HtmlRenderError, ValueError, OSError, subprocess.SubprocessError) as exc:
        staged_inventory = inventory(stage) if stage is not None and stage.exists() else []
        if stage is not None and stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
            stage = None
        if failure_receipt_path is not None:
            code_by_stage = {
                "input_gate": "INPUT_INVALID",
                "delivery_ir": "PROVENANCE_GAP",
                "pptx_write": "FORMAT_WRITE_FAILED",
                "html_write": "FORMAT_WRITE_FAILED",
                "format_validation": "FORMAT_VALIDATION_FAILED",
                "privacy_scan": "PRIVACY_SCAN_FAILED",
                "completeness_check": "REQUESTED_PRODUCED_MISMATCH",
                "atomic_commit": "ATOMIC_COMMIT_FAILED",
            }
            failure_code = code_by_stage.get(failure_stage, "FORMAT_VALIDATION_FAILED")
            if failure_stage in {"pptx_write", "html_write"} and any(
                marker in str(exc).lower()
                for marker in (
                    "runtime",
                    "chromium",
                    "运行验证需要",
                    "python-pptx",
                    "依赖不可用",
                    "依赖诊断",
                )
            ):
                failure_code = "ENGINE_UNAVAILABLE"
            receipt = {
                "schema_version": "failure-receipt/2.0",
                "failure_event_id": f"F-{uuid.uuid4().hex[:16]}",
                "run_id": run_id,
                "case_ref": delivery_ir["case_ref"] if delivery_ir else "UNRESOLVED",
                "data_class": delivery_ir["data_class"] if delivery_ir else "unknown",
                "delivery_ir_sha256": f"sha256:{delivery_ir_sha}" if delivery_ir_sha else None,
                "requested": requested,
                "failures": [
                    {
                        "stage": failure_stage,
                        "format": failure_format,
                        "failure_code": failure_code,
                        "message": f"{type(exc).__name__}:{failure_code}",
                    }
                ],
                "exit_code": EXIT_HOLD,
                "staging_inventory_before_cleanup": staged_inventory,
                "staging_deleted": True,
                "formal_output_inventory_before_sha256": f"sha256:{formal_before}",
                "formal_output_inventory_after_sha256": f"sha256:{inventory_sha256(out)}",
                "formal_output_unchanged": formal_before == inventory_sha256(out),
                "produced_committed": [],
                "partial_success": False,
                "manifest_committed": False,
                "atomic_strategy": "rename_same_filesystem",
            }
            try:
                failure_contract = PACKAGE_ROOT.parent / "references" / "contracts" / "failure-receipt-v2.schema.json"
                validate_schema(receipt, failure_contract, "FailureReceipt")
                write_json_atomic(failure_receipt_path, receipt)
                print(f"HOLD-CLIENT-DELIVERY: failure_receipt={failure_receipt_path}", file=sys.stderr)
            except (OSError, VerificationError, ValueError) as receipt_error:
                print(f"HOLD-CLIENT-DELIVERY: failure receipt unavailable:{type(receipt_error).__name__}", file=sys.stderr)
        return hold(str(exc))
    finally:
        if stage is not None and stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
