"""Stable source/render inventory for fail-closed semantic completeness checks."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
from typing import Any, Iterable, Mapping


SEMANTIC_ID_RE = re.compile(
    r"^sem:[A-Za-z0-9][A-Za-z0-9._:-]{0,63}:[a-z][a-z0-9_.-]{0,47}:\d{3}:[0-9a-f]{12}$"
)

ROLE_SLOTS: dict[str, tuple[str, ...]] = {
    "cover": (
        "profile.matter_label",
        "profile.client_label",
        "profile.materials_as_of",
        "profile.prepared_by",
        "profile.confidentiality",
    ),
    "executive_summary": ("items",),
    "relationship": ("parties", "chain"),
    "timeline": ("events", "undated_milestones"),
    "evidence_matrix": ("rows", "amounts", "amount_notes", "evidence_index"),
    "stage_risk": ("stages", "risks"),
    "next_steps": ("items", "gaps"),
    "scope": ("items",),
}
PROFILE_VISIBLE_SCALARS = (
    "client_label",
    "matter_label",
    "prepared_by",
    "materials_as_of",
    "confidentiality",
)
PROFILE_VISIBLE_LISTS = ("executive_summary", "next_steps", "scope_items")
PROFILE_CONTROL_FIELDS = (
    "schema",
    "case_ref",
    "internal_case_id_sha256",
    "data_class",
    "release_state",
)
SCOPE_BOUNDARY_ITEMS = (
    "本材料由自动化工具辅助整理，仅供律师与客户共同复核。",
    "未经事实、证据、现行法、隐私及指定律师终审，不构成法律意见。",
    "当前版本不是法院提交件，未经人工放行不得外发或标记为客户可交付。",
)
LAW_REVIEW_NOTICE_CELLS = (
    "提示",
    "待人工法律复核",
    "全部法条引用未注入",
    "人工终签",
)


class SemanticInventoryError(ValueError):
    """Raised when source or rendered semantic inventories do not close."""


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _resolve_slot(content: Mapping[str, Any], slot: str) -> list[Any]:
    if slot.startswith("profile."):
        profile = content.get("profile")
        if not isinstance(profile, Mapping):
            raise SemanticInventoryError("cover profile missing for semantic inventory")
        key = slot.split(".", 1)[1]
        if key not in profile:
            raise SemanticInventoryError(f"cover profile field missing:{key}")
        return [profile[key]]
    values = content.get(slot)
    if not isinstance(values, list):
        raise SemanticInventoryError(f"semantic slot must be an array:{slot}")
    return values


def build_source_inventory(slides: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Normalize all customer-visible domain items in deterministic render order."""

    inventory: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for slide in slides:
        slide_id = slide.get("slide_id")
        role = slide.get("role")
        content = slide.get("content")
        if not isinstance(slide_id, str) or not isinstance(role, str):
            raise SemanticInventoryError("slide id/role missing for semantic inventory")
        if role not in ROLE_SLOTS or not isinstance(content, Mapping):
            raise SemanticInventoryError(f"unsupported semantic slide role:{role}")
        title = slide.get("title")
        if not isinstance(title, str) or not title:
            raise SemanticInventoryError(f"slide title missing:{slide_id}")
        title_payload = {
            "slide_id": slide_id,
            "slot": "title",
            "item_index": 0,
            "value": title,
        }
        title_digest = hashlib.sha256(_canonical_bytes(title_payload)).hexdigest()
        title_semantic_id = f"sem:{slide_id}:title:001:{title_digest[:12]}"
        if not SEMANTIC_ID_RE.fullmatch(title_semantic_id):
            raise SemanticInventoryError(f"invalid semantic id:{title_semantic_id}")
        if title_semantic_id in seen_ids:
            raise SemanticInventoryError(
                f"duplicate source semantic id:{title_semantic_id}"
            )
        seen_ids.add(title_semantic_id)
        inventory.append(
            {
                "semantic_id": title_semantic_id,
                "slide_id": slide_id,
                "slot": "title",
                "item_index": 0,
                "content_sha256": f"sha256:{title_digest}",
            }
        )
        for slot in ROLE_SLOTS[role]:
            for item_index, item in enumerate(_resolve_slot(content, slot)):
                payload = {
                    "slide_id": slide_id,
                    "slot": slot,
                    "item_index": item_index,
                    "value": item,
                }
                digest = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
                semantic_id = (
                    f"sem:{slide_id}:{slot}:{item_index + 1:03d}:{digest[:12]}"
                )
                if not SEMANTIC_ID_RE.fullmatch(semantic_id):
                    raise SemanticInventoryError(f"invalid semantic id:{semantic_id}")
                if semantic_id in seen_ids:
                    raise SemanticInventoryError(f"duplicate source semantic id:{semantic_id}")
                seen_ids.add(semantic_id)
                inventory.append(
                    {
                        "semantic_id": semantic_id,
                        "slide_id": slide_id,
                        "slot": slot,
                        "item_index": item_index,
                        "content_sha256": f"sha256:{digest}",
                    }
                )
    if not inventory:
        raise SemanticInventoryError("semantic source inventory is empty")
    return inventory


def _exact_text_sha256(value: Any) -> str:
    if not isinstance(value, str):
        raise SemanticInventoryError("profile consumption value must be text")
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_value_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _slide_value(slide: Mapping[str, Any], slot: str, item_index: int) -> Any:
    if slot == "title":
        if item_index != 0:
            raise SemanticInventoryError("title semantic index must be zero")
        return slide.get("title")
    content = slide.get("content")
    if not isinstance(content, Mapping):
        raise SemanticInventoryError("slide content missing")
    if slot.startswith("profile."):
        profile = content.get("profile")
        key = slot.split(".", 1)[1]
        if not isinstance(profile, Mapping) or key not in profile or item_index != 0:
            raise SemanticInventoryError("cover profile semantic location invalid")
        return profile[key]
    values = content.get(slot)
    if not isinstance(values, list) or item_index >= len(values):
        raise SemanticInventoryError("semantic location missing from slide")
    return values[item_index]


def _closed_slide_title(
    slide: Mapping[str, Any], public_profile: Mapping[str, Any]
) -> str:
    slide_id = slide.get("slide_id")
    if slide_id == "cover-01":
        return str(public_profile.get("matter_label", ""))
    fixed = {
        "scope-00": "阅读须知与使用边界",
        "scope-01": "证据范围与放行边界",
    }
    if slide_id in fixed:
        return fixed[slide_id]
    families = (
        (r"executive-summary-(\d{2})", "客户沟通摘要"),
        (r"relationship-parties-(\d{2})", "案件主体"),
        (r"relationship-chain-(\d{2})", "交易链条"),
        (r"evidence-matrix-(\d{2})", "要件—事实—证据矩阵"),
        (r"evidence-amounts-(\d{2})", "金额口径"),
        (r"evidence-amount-notes-(\d{2})", "金额口径说明"),
        (r"evidence-index-(\d{2})", "证据索引"),
        (r"stage-plan-(\d{2})", "程序阶段计划"),
        (r"risk-register-(\d{2})", "风险与暂停事项"),
        (r"next-actions-(\d{2})", "下一步行动"),
        (r"evidence-gaps-(\d{2})", "待核与证据缺口"),
    )
    if isinstance(slide_id, str):
        timeline = re.fullmatch(r"timeline-(\d{2})", slide_id)
        if timeline:
            content = slide.get("content")
            if not isinstance(content, Mapping):
                raise SemanticInventoryError("timeline content missing")
            ordinal = int(timeline.group(1))
            if not content.get("events") and content.get("undated_milestones"):
                return "未系日期事项"
            return "关键事件时间线" + (f"（续 {ordinal}）" if ordinal > 1 else "")
        for pattern, base in families:
            matched = re.fullmatch(pattern, slide_id)
            if matched:
                ordinal = int(matched.group(1))
                return base + (f"（续 {ordinal}）" if ordinal > 1 else "")
    raise SemanticInventoryError(f"unregistered closed slide title:{slide_id}")


def _require_consumption_ledgers(
    delivery_ir: Mapping[str, Any], inventory: list[dict[str, Any]]
) -> None:
    """Require source/profile/derived ledgers to partition all semantics exactly."""

    slides = delivery_ir.get("slides")
    if not isinstance(slides, list) or not all(isinstance(slide, Mapping) for slide in slides):
        raise SemanticInventoryError("DeliveryIR slides missing for ledger validation")
    slide_by_id = {slide.get("slide_id"): slide for slide in slides}
    if len(slide_by_id) != len(slides):
        raise SemanticInventoryError("duplicate slide id in ledger validation")
    semantic_by_location = {
        (item["slide_id"], item["slot"], item["item_index"]): item
        for item in inventory
    }

    def require_projection(projection: Any, label: str) -> tuple[str, str, int]:
        if not isinstance(projection, Mapping):
            raise SemanticInventoryError(f"invalid {label} projection")
        location = (
            projection.get("slide_id"),
            projection.get("slot"),
            projection.get("item_index"),
        )
        semantic = semantic_by_location.get(location)
        if semantic is None or any(
            projection.get(key) != semantic[key]
            for key in (
                "slide_id",
                "slot",
                "item_index",
                "semantic_id",
                "content_sha256",
            )
        ):
            raise SemanticInventoryError(f"stale {label} projection:{location}")
        return location

    source_ledger = delivery_ir.get("source_consumption")
    if not isinstance(source_ledger, Mapping):
        raise SemanticInventoryError("DeliveryIR source consumption ledger missing")
    source_items = source_ledger.get("items")
    if not isinstance(source_items, list):
        raise SemanticInventoryError("DeliveryIR source consumption items missing")
    source_locations: list[tuple[str, str, int]] = []
    source_keys: list[tuple[Any, Any]] = []
    for item in source_items:
        if not isinstance(item, Mapping) or not isinstance(item.get("projections"), list):
            raise SemanticInventoryError("invalid source consumption item")
        source_keys.append((item.get("source_id"), item.get("source_locator")))
        source_locations.extend(
            require_projection(projection, "source consumption")
            for projection in item["projections"]
        )
    if len(source_keys) != len(set(source_keys)):
        raise SemanticInventoryError("duplicate source occurrence")
    if len(source_locations) != len(set(source_locations)):
        raise SemanticInventoryError("duplicate source consumption projection")
    if (
        source_ledger.get("candidate_item_count") != len(source_items)
        or source_ledger.get("consumed_item_count") != len(source_items)
        or source_ledger.get("total_projection_count") != len(source_locations)
        or source_ledger.get("coverage_percent") != 100
        or source_ledger.get("unconsumed_item_count") != 0
        or source_ledger.get("undeclared_duplicate_count") != 0
    ):
        raise SemanticInventoryError("source consumption ledger counts are stale")

    profile_ledger = delivery_ir.get("profile_consumption")
    if not isinstance(profile_ledger, Mapping):
        raise SemanticInventoryError("DeliveryIR profile consumption ledger missing")
    profile_items = profile_ledger.get("items")
    if not isinstance(profile_items, list):
        raise SemanticInventoryError("DeliveryIR profile consumption items missing")
    public_profile = delivery_ir.get("profile")
    if not isinstance(public_profile, Mapping):
        raise SemanticInventoryError("DeliveryIR public profile missing")
    profile_locations: list[tuple[str, str, int]] = []
    profile_source_keys: list[tuple[str, int]] = []
    declared_profile_bindings: list[tuple[str, int, tuple[str, str, int]]] = []
    denominator: list[dict[str, Any]] = []
    for item in profile_items:
        if not isinstance(item, Mapping):
            raise SemanticInventoryError("invalid profile consumption item")
        field = item.get("field")
        source_index = item.get("source_index")
        source_sha256 = item.get("source_sha256")
        if not isinstance(field, str) or not isinstance(source_index, int):
            raise SemanticInventoryError("invalid profile source occurrence")
        profile_source_keys.append((field, source_index))
        denominator.append(
            {
                "field": field,
                "source_index": source_index,
                "source_sha256": source_sha256,
            }
        )
        if field in PROFILE_VISIBLE_SCALARS:
            if source_index != 0 or field not in public_profile:
                raise SemanticInventoryError("invalid scalar profile occurrence")
            if source_sha256 != _exact_text_sha256(public_profile[field]):
                raise SemanticInventoryError("stale scalar profile source hash")
        location = require_projection(item.get("projection"), "profile consumption")
        profile_locations.append(location)
        declared_profile_bindings.append((field, source_index, location))
    if len(profile_source_keys) != len(set(profile_source_keys)):
        raise SemanticInventoryError("duplicate profile source occurrence")
    if len(profile_locations) != len(set(profile_locations)):
        raise SemanticInventoryError("duplicate profile consumption projection")

    expected_profile_bindings: list[tuple[str, int, tuple[str, str, int]]] = [
        (field, 0, ("cover-01", f"profile.{field}", 0))
        for field in PROFILE_VISIBLE_SCALARS
    ]
    profile_slide_groups = {
        "executive_summary": [
            slide for slide in slides if slide.get("role") == "executive_summary"
        ],
        "next_steps": [
            slide
            for slide in slides
            if isinstance(slide.get("slide_id"), str)
            and slide["slide_id"].startswith("next-actions-")
        ],
        "scope_items": [
            slide
            for slide in slides
            if slide.get("role") == "scope" and slide.get("slide_id") != "scope-00"
        ],
    }
    for field in PROFILE_VISIBLE_LISTS:
        source_index = 0
        for slide in profile_slide_groups[field]:
            content = slide.get("content")
            values = content.get("items") if isinstance(content, Mapping) else None
            if not isinstance(values, list):
                raise SemanticInventoryError(f"profile target items missing:{field}")
            for item_index, _value in enumerate(values):
                expected_profile_bindings.append(
                    (
                        field,
                        source_index,
                        (slide["slide_id"], "items", item_index),
                    )
                )
                source_index += 1
    if declared_profile_bindings != expected_profile_bindings:
        raise SemanticInventoryError("profile consumption target map is stale")
    denominator_digest = "sha256:" + hashlib.sha256(_canonical_bytes(denominator)).hexdigest()
    if profile_ledger.get("denominator_sha256") != denominator_digest:
        raise SemanticInventoryError("profile consumption denominator is stale")
    if (
        profile_ledger.get("scope")
        != [*PROFILE_VISIBLE_SCALARS, *PROFILE_VISIBLE_LISTS]
        or profile_ledger.get("candidate_item_count") != len(profile_items)
        or profile_ledger.get("consumed_item_count") != len(profile_items)
        or profile_ledger.get("total_projection_count") != len(profile_locations)
        or profile_ledger.get("coverage_percent") != 100
        or profile_ledger.get("unconsumed_item_count") != 0
        or profile_ledger.get("undeclared_duplicate_count") != 0
    ):
        raise SemanticInventoryError("profile consumption ledger counts are stale")

    control_values = {
        "schema": public_profile.get("schema"),
        "case_ref": delivery_ir.get("case_ref"),
        "data_class": delivery_ir.get("data_class"),
        "release_state": delivery_ir.get("release_state"),
    }
    excluded_controls = profile_ledger.get("excluded_controls")
    if not isinstance(excluded_controls, list):
        raise SemanticInventoryError("profile control exclusions missing")
    excluded_fields: list[Any] = []
    for item in excluded_controls:
        if not isinstance(item, Mapping):
            raise SemanticInventoryError("invalid profile control exclusion")
        field = item.get("field")
        excluded_fields.append(field)
        if item.get("excluded_reason") != "non_customer_visible_control":
            raise SemanticInventoryError("invalid profile control exclusion reason")
        if field in control_values and item.get("source_sha256") != _exact_text_sha256(
            control_values[field]
        ):
            raise SemanticInventoryError("stale profile control source hash")
    if (
        excluded_fields != [*PROFILE_CONTROL_FIELDS]
        or profile_ledger.get("control_scope") != [*PROFILE_CONTROL_FIELDS]
        or profile_ledger.get("excluded_control_count") != len(excluded_controls)
    ):
        raise SemanticInventoryError("profile control exclusion set is stale")

    derived_ledger = delivery_ir.get("derived_consumption")
    if not isinstance(derived_ledger, Mapping):
        raise SemanticInventoryError("DeliveryIR derived consumption ledger missing")
    derived_items = derived_ledger.get("items")
    if not isinstance(derived_items, list):
        raise SemanticInventoryError("DeliveryIR derived consumption items missing")
    derived_locations: list[tuple[str, str, int]] = []
    declared_derived: dict[str, tuple[str, str, tuple[str, str, int]]] = {}
    for item in derived_items:
        if not isinstance(item, Mapping) or not isinstance(item.get("derived_id"), str):
            raise SemanticInventoryError("invalid derived consumption item")
        derived_id = item["derived_id"]
        if derived_id in declared_derived:
            raise SemanticInventoryError("duplicate derived consumption id")
        location = require_projection(item.get("projection"), "derived consumption")
        derived_locations.append(location)
        declared_derived[derived_id] = (
            item.get("derived_reason"),
            item.get("value_sha256"),
            location,
        )
    if len(derived_locations) != len(set(derived_locations)):
        raise SemanticInventoryError("duplicate derived consumption projection")

    expected_derived: dict[str, tuple[str, str, tuple[str, str, int]]] = {}
    for item_index, value in enumerate(SCOPE_BOUNDARY_ITEMS):
        expected_derived[f"scope-boundary-{item_index + 1:03d}"] = (
            "fixed_review_boundary",
            _canonical_value_sha256(value),
            ("scope-00", "items", item_index),
        )
    for slide in slides:
        expected_title = _closed_slide_title(slide, public_profile)
        if slide.get("title") != expected_title:
            raise SemanticInventoryError(f"closed slide title mismatch:{slide.get('slide_id')}")
        expected_derived[f"slide-title:{slide['slide_id']}"] = (
            "closed_slide_title",
            _canonical_value_sha256(expected_title),
            (slide["slide_id"], "title", 0),
        )

    a09_risk_values: list[Any] = []
    for item in source_items:
        if item.get("source_id") != "A09":
            continue
        for projection in item.get("projections", []):
            if projection.get("slot") != "risks":
                continue
            slide = slide_by_id.get(projection.get("slide_id"))
            if not isinstance(slide, Mapping):
                raise SemanticInventoryError("A09 risk slide missing")
            a09_risk_values.append(
                _slide_value(slide, "risks", projection["item_index"])
            )
    needs_law_notice = not any(
        "法条" in json.dumps(value, ensure_ascii=False)
        or "法源" in json.dumps(value, ensure_ascii=False)
        for value in a09_risk_values
    )
    if needs_law_notice:
        notice_value = {"cells": list(LAW_REVIEW_NOTICE_CELLS)}
        notice_locations = [
            location
            for location in semantic_by_location
            if location[1] == "risks"
            and location not in source_locations
            and _slide_value(slide_by_id[location[0]], location[1], location[2])
            == notice_value
        ]
        if len(notice_locations) != 1:
            raise SemanticInventoryError("closed law-review notice missing or duplicated")
        expected_derived["missing-legal-authority-notice"] = (
            "missing_legal_authority_notice",
            _canonical_value_sha256(notice_value),
            notice_locations[0],
        )
    if declared_derived != expected_derived:
        raise SemanticInventoryError("derived consumption set is stale")
    if (
        derived_ledger.get("candidate_item_count") != len(derived_items)
        or derived_ledger.get("consumed_item_count") != len(derived_items)
        or derived_ledger.get("total_projection_count") != len(derived_locations)
        or derived_ledger.get("coverage_percent") != 100
        or derived_ledger.get("unconsumed_item_count") != 0
        or derived_ledger.get("undeclared_duplicate_count") != 0
    ):
        raise SemanticInventoryError("derived consumption ledger counts are stale")

    semantic_locations = [
        (item["slide_id"], item["slot"], item["item_index"])
        for item in inventory
    ]
    partition_locations = [*source_locations, *profile_locations, *derived_locations]
    overlap_count = sum(
        count - 1 for count in Counter(partition_locations).values() if count > 1
    )
    unpartitioned_count = sum(
        (Counter(semantic_locations) - Counter(partition_locations)).values()
    )
    unexpected_count = sum(
        (Counter(partition_locations) - Counter(semantic_locations)).values()
    )
    if overlap_count or unpartitioned_count or unexpected_count:
        raise SemanticInventoryError(
            "semantic projection partition is not exact:"
            f"overlap={overlap_count};unpartitioned={unpartitioned_count};"
            f"unexpected={unexpected_count}"
        )
    expected_partition = {
        "schema": "domain-projection-partition/1.0",
        "semantic_item_count": len(semantic_locations),
        "source_projection_count": len(source_locations),
        "profile_projection_count": len(profile_locations),
        "derived_projection_count": len(derived_locations),
        "partitioned_item_count": len(partition_locations),
        "overlap_count": 0,
        "unpartitioned_item_count": 0,
        "unexpected_projection_count": 0,
        "semantic_inventory_sha256": _canonical_value_sha256(inventory),
    }
    if delivery_ir.get("domain_projection_partition") != expected_partition:
        raise SemanticInventoryError("domain projection partition receipt is stale")


def require_source_inventory(delivery_ir: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Recompute the normalized source inventory and reject a forged/stale copy."""

    slides = delivery_ir.get("slides")
    declared = delivery_ir.get("semantic_inventory")
    if not isinstance(slides, list) or not isinstance(declared, list):
        raise SemanticInventoryError("DeliveryIR semantic inventory missing")
    expected = build_source_inventory(slides)
    if declared != expected:
        raise SemanticInventoryError("DeliveryIR semantic inventory is stale or non-canonical")
    if delivery_ir.get("schema") == "delivery-ir/1.0":
        _require_consumption_ledgers(delivery_ir, expected)
    return expected


def semantic_lookup(delivery_ir: Mapping[str, Any]) -> dict[tuple[str, str, int], str]:
    return {
        (item["slide_id"], item["slot"], item["item_index"]): item["semantic_id"]
        for item in require_source_inventory(delivery_ir)
    }


def _inventory_digest(ids: list[str]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(ids)).hexdigest()


def compare_rendered_inventory(
    delivery_ir: Mapping[str, Any], rendered_ids: Iterable[str], *, artifact_format: str
) -> dict[str, Any]:
    """Compare independently extracted artifact IDs to the normalized source order."""

    expected_items = require_source_inventory(delivery_ir)
    expected = [item["semantic_id"] for item in expected_items]
    rendered = list(rendered_ids)
    expected_set = set(expected)
    counts = Counter(rendered)
    duplicates = sorted(item for item, count in counts.items() if count > 1)
    missing = [item for item in expected if item not in counts]
    unexpected = [item for item in rendered if item not in expected_set]
    reordered = (
        not missing
        and not unexpected
        and not duplicates
        and rendered != expected
    )
    status = not missing and not unexpected and not duplicates and not reordered
    receipt = {
        "artifact_format": artifact_format,
        "source_item_count": len(expected),
        "rendered_item_count": len(rendered),
        "source_inventory_sha256": _inventory_digest(expected),
        "rendered_inventory_sha256": _inventory_digest(rendered),
        "missing_ids": missing,
        "duplicate_ids": duplicates,
        "unexpected_ids": unexpected,
        "reordered": reordered,
        "status": "complete" if status else "SILENT_TRUNCATION_DETECTED",
    }
    if not status:
        raise SemanticInventoryError(
            "SILENT_TRUNCATION_DETECTED:"
            f"format={artifact_format};missing={len(missing)};"
            f"duplicate={len(duplicates)};unexpected={len(unexpected)};"
            f"reordered={str(reordered).lower()}"
        )
    return receipt
