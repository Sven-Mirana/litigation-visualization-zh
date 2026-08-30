"""Strict input gate for the S2 client-delivery runner.

The renderer receives bytes and a redacted profile, never source paths.  All
paths are resolved and verified before the first output byte is written.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import date
from pathlib import Path
from typing import Any


PATH_ERRORS = (OSError, RuntimeError, ValueError)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CASE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
PROFILE_SCHEMA = "client-delivery-profile/1.0"
ALLOWED_DATA_CLASSES = {"synthetic", "deidentified"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CONFIDENTIALITY = {"CONFIDENTIAL", "ATTORNEY_WORK_PRODUCT", "INTERNAL_REVIEW_ONLY"}


class GateError(ValueError):
    """Raised when a client-delivery input is not safe to consume."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
    )


def _reject_constant(value: str) -> None:
    raise GateError(f"JSON含非法常量:{value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GateError(f"JSON含重复键:{key}")
        result[key] = value
    return result


def strict_json_bytes(raw: bytes, label: str) -> Any:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GateError(f"{label}不是有效UTF-8") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, TypeError) as exc:
        raise GateError(f"{label}不是严格JSON:{type(exc).__name__}") from exc


def strict_json_file(path: Path, label: str) -> tuple[Any, bytes]:
    try:
        if path.is_symlink() or not path.is_file():
            raise GateError(f"{label}缺失或为symlink")
        raw = path.read_bytes()
    except PATH_ERRORS as exc:
        if isinstance(exc, GateError):
            raise
        raise GateError(f"{label}不可读取:{type(exc).__name__}") from exc
    return strict_json_bytes(raw, label), raw


def _within(path: Path, root: Path) -> bool:
    if path == root or root in path.parents:
        return True
    cursor = path
    while True:
        try:
            if cursor.exists() and os.path.samefile(cursor, root):
                return True
        except PATH_ERRORS:
            pass
        if cursor == cursor.parent:
            return False
        cursor = cursor.parent


def _regular_file(path: Path) -> bool:
    try:
        return not path.is_symlink() and stat.S_ISREG(
            path.stat(follow_symlinks=False).st_mode
        )
    except PATH_ERRORS:
        return False


def _nonempty_text_list(value: Any, label: str, *, maximum: int = 48) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > maximum:
        raise GateError(f"{label}必须是1-{maximum}项字符串数组")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip() or len(item) > 600:
            raise GateError(f"{label}[{index}]不是合格文本")
        result.append(item.strip())
    return result


def validate_profile(profile: Any, internal_case_id: str) -> dict[str, Any]:
    if not isinstance(profile, dict):
        raise GateError("交付profile必须为JSON对象")
    allowed = {
        "schema",
        "case_ref",
        "internal_case_id_sha256",
        "data_class",
        "release_state",
        "client_label",
        "matter_label",
        "materials_as_of",
        "confidentiality",
        "prepared_by",
        "executive_summary",
        "next_steps",
        "scope_items",
    }
    unknown = sorted(set(profile) - allowed)
    if unknown:
        raise GateError(f"交付profile含未注册字段:{','.join(unknown)}")
    if profile.get("schema") != PROFILE_SCHEMA:
        raise GateError("交付profile schema不符")
    case_ref = profile.get("case_ref")
    if not isinstance(case_ref, str) or not CASE_REF_RE.fullmatch(case_ref):
        raise GateError("case_ref必须为匿名稳定标识")
    expected_case_hash = sha256_bytes(internal_case_id.encode("utf-8"))
    if profile.get("internal_case_id_sha256") != expected_case_hash:
        raise GateError("交付profile未绑定当前内部case-id")
    data_class = profile.get("data_class")
    if data_class not in ALLOWED_DATA_CLASSES:
        raise GateError("data_class无效")
    if profile.get("release_state") != "REVIEW_DRAFT":
        raise GateError("S2候选仅允许review_draft；CLIENT-READY需另行人工放行")
    text_fields = (
        "client_label",
        "matter_label",
        "materials_as_of",
        "confidentiality",
        "prepared_by",
    )
    clean: dict[str, Any] = {
        "schema": PROFILE_SCHEMA,
        "case_ref": case_ref,
        # Retain the already verified binding in the canonical validated
        # profile.  It is not customer-visible, but profile-consumption/1.0
        # must be able to account for every accepted control occurrence.
        "internal_case_id_sha256": expected_case_hash,
        "data_class": data_class,
        "release_state": "REVIEW_DRAFT",
    }
    for field in text_fields:
        value = profile.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > 160:
            raise GateError(f"交付profile字段无效:{field}")
        if "/Users/" in value or "file://" in value or "\\" in value:
            raise GateError(f"交付profile字段疑似泄漏路径:{field}")
        clean[field] = value.strip()
    if not DATE_RE.fullmatch(clean["materials_as_of"]):
        raise GateError("materials_as_of必须为YYYY-MM-DD")
    try:
        date.fromisoformat(clean["materials_as_of"])
    except ValueError as exc:
        raise GateError("materials_as_of不是有效日历日期") from exc
    if clean["confidentiality"] not in CONFIDENTIALITY:
        raise GateError("confidentiality无效")
    clean["executive_summary"] = _nonempty_text_list(
        profile.get("executive_summary"), "executive_summary", maximum=16
    )
    clean["next_steps"] = _nonempty_text_list(
        profile.get("next_steps"), "next_steps", maximum=24
    )
    clean["scope_items"] = _nonempty_text_list(
        profile.get("scope_items"), "scope_items", maximum=16
    )
    return clean


def load_inputs(
    *,
    case_id: str,
    frozen07_dir: str,
    text_pass_receipt: str,
    delivery_profile: str,
) -> dict[str, Any]:
    """Return verified bytes and a renderer-safe profile."""

    if not isinstance(case_id, str) or not case_id or "\x00" in case_id:
        raise GateError("case-id无效")
    try:
        receipt_path = Path(text_pass_receipt).expanduser()
        profile_path = Path(delivery_profile).expanduser()
        frozen_input = Path(frozen07_dir).expanduser()
        if frozen_input.is_symlink():
            raise GateError("冻结07目录不得为symlink")
        frozen_root = frozen_input.resolve(strict=True)
    except PATH_ERRORS as exc:
        if isinstance(exc, GateError):
            raise
        raise GateError(f"输入路径不可解析:{type(exc).__name__}") from exc
    if not frozen_root.is_dir():
        raise GateError("冻结07目录缺失")

    receipt, _receipt_raw = strict_json_file(receipt_path, "TEXT-PASS收据")
    if not isinstance(receipt, dict) or receipt.get("result") != "PASS":
        raise GateError("TEXT-PASS收据未通过")
    if receipt.get("case_id") != case_id:
        raise GateError("TEXT-PASS收据跨案")

    manifest_path = frozen_root / "FROZEN-07-MANIFEST.json"
    manifest, _manifest_raw = strict_json_file(manifest_path, "冻结07 manifest")
    if not isinstance(manifest, dict) or manifest.get("case_id") != case_id:
        raise GateError("冻结07 manifest跨案或无效")
    relative = manifest.get("md_relpath")
    digest = manifest.get("md_sha256")
    if (
        not isinstance(relative, str)
        or not relative
        or "\x00" in relative
        or Path(relative).is_absolute()
    ):
        raise GateError("冻结07 md_relpath无效")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest.lower()):
        raise GateError("冻结07 md_sha256无效")
    cursor = frozen_root
    try:
        for part in Path(relative).parts:
            if part in {"", ".", ".."}:
                raise GateError("冻结07 md_relpath未规范化")
            cursor = cursor / part
            if cursor.is_symlink():
                raise GateError("冻结07路径不得含symlink")
        markdown_path = (frozen_root / relative).resolve(strict=True)
    except PATH_ERRORS as exc:
        if isinstance(exc, GateError):
            raise
        raise GateError(f"冻结07路径不可解析:{type(exc).__name__}") from exc
    if not _within(markdown_path, frozen_root) or not _regular_file(markdown_path):
        raise GateError("冻结07文件越界或不是普通文件")
    try:
        markdown_bytes = markdown_path.read_bytes()
    except PATH_ERRORS as exc:
        raise GateError(f"冻结07不可读取:{type(exc).__name__}") from exc
    if sha256_bytes(markdown_bytes) != digest.lower():
        raise GateError("冻结07哈希不符")
    try:
        markdown_text = markdown_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GateError("冻结07不是有效UTF-8") from exc

    profile_raw_value, _profile_raw = strict_json_file(profile_path, "交付profile")
    profile = validate_profile(profile_raw_value, case_id)
    profile_sha256 = sha256_bytes(canonical_json_bytes(profile))
    return {
        "case_id": case_id,
        "input_sha256": sha256_bytes(markdown_bytes),
        "markdown_text": markdown_text,
        "profile": profile,
        "profile_sha256": profile_sha256,
    }
