"""Build a redacted, deterministic, zero-truncation DeliveryIR from frozen 07."""

from __future__ import annotations

from collections import Counter
from datetime import date
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from typing import Any, Iterable

from .semantic_inventory import build_source_inventory


RELATIONSHIP_PARTIES_PER_SLIDE = 6
RELATIONSHIP_CHAIN_PER_SLIDE = 3
TIMELINE_EVENTS_PER_SLIDE = 4
MATRIX_ROWS_PER_SLIDE = 3
AMOUNTS_PER_SLIDE = 3
EVIDENCE_PER_SLIDE = 4
STAGES_PER_SLIDE = 4
RISKS_PER_SLIDE = 3
NEXT_STEPS_PER_SLIDE = 5
GAPS_PER_SLIDE = 4

SOURCE_LAYOUT_HEADERS: dict[str, dict[str, tuple[str, ...]]] = {
    "canonical-v1": {
        "A01": ("主体", "角色", "要点", "来源"),
        "A04": ("项目", "金额（元）", "口径"),
        "A06": ("要件", "事实", "证据", "缺口", "状态"),
        "A08": ("阶段", "动作", "出口"),
        "A09": ("编号", "类别", "内容", "解除条件"),
    },
    "legacy-frozen07-v1": {
        "A01": ("角色", "主体", "说明"),
        "A04": ("口径", "项目", "金额（万元）", "说明"),
        "A06": ("要件", "事实主张", "对应证据", "状态", "备注"),
        "A08": ("阶段", "主要动作", "时点"),
        "A09": ("风险事项", "等级", "说明", "处置"),
    },
}
TABLE_HEADER_VARIANTS: dict[str, tuple[tuple[str, ...], ...]] = {
    anchor_id: tuple(
        layout[anchor_id] for layout in SOURCE_LAYOUT_HEADERS.values()
    )
    for anchor_id in ("A01", "A04", "A06", "A08", "A09")
}

# A04's established four-column layout may carry a prose qualification after
# its table.  That prose is allowed only for this exact header, only after a
# blank boundary following at least one data row, and is routed into the same
# occurrence/projection ledger as every other substantive source line.
TRAILING_PROSE_TABLE_HEADERS = {
    ("A04", ("口径", "项目", "金额（万元）", "说明")),
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
DATE_RE = re.compile(
    r"(?<!\d)(?:(\d{4})-(\d{1,2})-(\d{1,2})|"
    r"(\d{4})年(\d{1,2})月(\d{1,2})日)(?!\d)"
)
DATE_LIKE_RE = re.compile(
    r"(?<!\d)\d{4}(?:-|年)\d{1,2}(?:-|月)\d{1,2}(?:日)?(?!\d)"
)


def _load_builder(package_root: Path):
    path = package_root / "viz-engine" / "mother-build_t4.py"
    spec = importlib.util.spec_from_file_location("s2_frozen_mother_build_t4", path)
    if spec is None or spec.loader is None:
        raise ValueError("无法加载冻结S1构建器")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    if not items:
        return [[]]
    return [items[index : index + size] for index in range(0, len(items), size)]


def _paired_chunks(
    first: list[Any], first_size: int, second: list[Any], second_size: int
) -> list[tuple[list[Any], list[Any]]]:
    first_parts = _chunks(first, first_size)
    second_parts = _chunks(second, second_size)
    count = max(len(first_parts), len(second_parts))
    return [
        (
            first_parts[index] if index < len(first_parts) else [],
            second_parts[index] if index < len(second_parts) else [],
        )
        for index in range(count)
    ]


def _balanced_chunks(items: list[Any], maximum_size: int) -> list[list[Any]]:
    """Split into the fewest pages while balancing adjacent page density.

    A capacity of six therefore yields 7 -> 4+3, 8 -> 4+4, ...,
    11 -> 6+5 instead of a crowded first page followed by a singleton.
    """

    if maximum_size < 1:
        raise ValueError("分页容量必须为正整数")
    if not items:
        return [[]]
    page_count = (len(items) + maximum_size - 1) // maximum_size
    base_size, larger_pages = divmod(len(items), page_count)
    result: list[list[Any]] = []
    offset = 0
    for index in range(page_count):
        page_size = base_size + (1 if index < larger_pages else 0)
        result.append(items[offset : offset + page_size])
        offset += page_size
    if offset != len(items):
        raise ValueError("均衡分页未完整消费输入")
    return result


def _preserve_source_stars(value: str) -> str:
    """Preserve source stars verbatim; privacy masks outrank styling hints."""

    return value


def _normalize_prose_line(line: str, anchor_id: str) -> str:
    value = line.strip()
    if not value:
        raise ValueError(f"{anchor_id}空行不是源候选项")
    if value.startswith("## "):
        raise ValueError(f"{anchor_id}存在未路由子标题")
    if value.startswith("|"):
        raise ValueError(f"{anchor_id}仅允许实质散文行，不接受未路由表格")
    normalized = _preserve_source_stars(value)
    # A hyphen is a bullet only when followed by whitespace.  Without that
    # proof it may be a legally material negative amount and must survive.
    normalized = re.sub(r"^(?:-\s+|·\s*)", "", normalized)
    # ASCII/full-width dots are also decimal separators.  Only whitespace
    # proves enumeration; the Chinese dunhao is unambiguous without it.
    normalized = re.sub(r"^(?:\d+[.．]\s+|\d+、\s*)", "", normalized)
    if not normalized:
        raise ValueError(f"{anchor_id}实质行规范化后为空")
    return normalized


def _substantive_lines(segment: str) -> list[str]:
    result: list[str] = []
    for line in segment.splitlines()[1:]:
        if not line.strip():
            continue
        result.append(_normalize_prose_line(line, "SOURCE"))
    return result


def _table_cells(line: str) -> list[str] | None:
    """Return one safely normalized source table row."""

    if not line.startswith("|") or not line.endswith("|"):
        return None
    return [
        _preserve_source_stars(cell.strip())
        for cell in line.strip("|").split("|")
    ]


def _separator_width(line: str) -> int | None:
    if not line.startswith("|") or not line.endswith("|"):
        return None
    cells = [cell.strip() for cell in line.strip("|").split("|")]
    if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
        return len(cells)
    return None


def _first_table_header(segment: str, anchor_id: str) -> tuple[str, ...]:
    lines = segment.splitlines()
    nonblank = [index for index in range(1, len(lines)) if lines[index].strip()]
    if not nonblank:
        raise ValueError(f"{anchor_id}缺少固定表头")
    header = _table_cells(lines[nonblank[0]])
    if header is None:
        raise ValueError(f"{anchor_id}固定表头不匹配")
    return tuple(header)


def _resolve_source_layout_variant(sections: dict[str, str]) -> str:
    """Accept one complete, exact table-layout family and reject hybrids."""

    observed = {
        anchor_id: _first_table_header(sections[anchor_id], anchor_id)
        for anchor_id in ("A01", "A04", "A06", "A08", "A09")
    }
    invalid = [
        anchor_id
        for anchor_id, header in observed.items()
        if header not in TABLE_HEADER_VARIANTS[anchor_id]
    ]
    if invalid:
        raise ValueError(f"{invalid[0]}固定表头不匹配")
    matches = [
        variant
        for variant, headers in SOURCE_LAYOUT_HEADERS.items()
        if observed == headers
    ]
    if len(matches) != 1:
        raise ValueError("A01/A04/A06/A08/A09固定表头变体混用")
    return matches[0]


def source_schema_for_variant(layout_variant: str) -> dict[str, Any]:
    headers = SOURCE_LAYOUT_HEADERS.get(layout_variant)
    if headers is None:
        raise ValueError(f"未知源布局变体:{layout_variant}")
    return {
        "schema": "frozen07-source-schema/1.0",
        "variant": layout_variant,
        "table_headers": {
            anchor_id: list(header) for anchor_id, header in headers.items()
        },
    }


def require_source_schema(source_schema: Any) -> dict[str, Any]:
    """Reject forged variant labels, per-anchor headers, and hybrid schemas."""

    if not isinstance(source_schema, dict):
        raise ValueError("DeliveryIR缺少源布局契约")
    variant = source_schema.get("variant")
    if not isinstance(variant, str):
        raise ValueError("DeliveryIR源布局变体无效")
    expected = source_schema_for_variant(variant)
    if source_schema != expected:
        raise ValueError("DeliveryIR源布局表头与变体不一致")
    return expected


def visible_table_headers(source_schema: Any) -> dict[str, list[str]]:
    """Return exact source-native headers from a closed DeliveryIR schema."""

    headers = require_source_schema(source_schema)["table_headers"]
    return {
        "matrix": list(headers["A06"]),
        "amounts": list(headers["A04"]),
        "stages": list(headers["A08"]),
        "risks": list(headers["A09"]),
    }


def _table_structure(
    segment: str, anchor_id: str
) -> tuple[
    int,
    int,
    tuple[str, ...],
    list[tuple[int, list[str]]],
    list[tuple[int, str]],
]:
    allowed_headers = TABLE_HEADER_VARIANTS.get(anchor_id)
    if not allowed_headers:
        raise ValueError(f"{anchor_id}无固定表头契约")
    lines = segment.splitlines()
    nonblank = [index for index in range(1, len(lines)) if lines[index].strip()]
    if not nonblank:
        raise ValueError(f"{anchor_id}缺少固定表头")
    header_index = nonblank[0]
    header = _table_cells(lines[header_index])
    matched_header = next(
        (
            candidate
            for candidate in allowed_headers
            if header == list(candidate)
        ),
        None,
    )
    if matched_header is None:
        raise ValueError(f"{anchor_id}固定表头不匹配")
    expected_width = len(matched_header)
    separator_index = header_index + 1
    if (
        separator_index >= len(lines)
        or _separator_width(lines[separator_index]) != expected_width
    ):
        raise ValueError(f"{anchor_id}固定表头后缺少合法紧邻分隔行")

    data_rows: list[tuple[int, list[str]]] = []
    prose_rows: list[tuple[int, str]] = []
    prose_started = False
    blank_after_data = False
    trailing_prose_allowed = (anchor_id, matched_header) in TRAILING_PROSE_TABLE_HEADERS
    for line_index in range(separator_index + 1, len(lines)):
        line = lines[line_index]
        if not line.strip():
            if data_rows:
                blank_after_data = True
            continue
        if _separator_width(line) is not None:
            raise ValueError(f"{anchor_id}存在额外或错位分隔行")
        cells = _table_cells(line)
        if cells is not None:
            if prose_started:
                raise ValueError(f"{anchor_id}尾随散文后禁止恢复表格")
            row_index = len(data_rows) + 1
            if len(cells) != expected_width:
                raise ValueError(
                    f"{anchor_id}第{row_index}行列数必须为{expected_width}:"
                    f"actual={len(cells)}"
                )
            data_rows.append((line_index, cells))
            continue
        if not trailing_prose_allowed:
            raise ValueError(f"{anchor_id}仅允许固定宽度表格，存在未路由实质行")
        if not data_rows or not blank_after_data:
            raise ValueError(f"{anchor_id}尾随散文必须位于完整表格后的独立段落")
        normalized = _normalize_prose_line(line, anchor_id)
        prose_started = True
        prose_rows.append((line_index, normalized))
    if trailing_prose_allowed and len(prose_rows) != 1:
        raise ValueError(
            f"{anchor_id}授权尾随说明必须且只能有一条:actual={len(prose_rows)}"
        )
    return header_index, separator_index, matched_header, data_rows, prose_rows


def _structural_exclusions(
    segment: str, anchor_id: str, has_table: bool = False
) -> list[dict[str, Any]]:
    """Hash structural markdown occurrences that are deliberately not routed."""

    lines = segment.splitlines()
    if not lines or not lines[0].startswith("## "):
        raise ValueError(f"{anchor_id}缺少锚标题结构")
    reasons = {0: "anchor_title"}
    if has_table:
        header_index, separator_index, _, _, _ = _table_structure(
            segment, anchor_id
        )
        reasons[header_index] = "table_header"
        reasons[separator_index] = "table_separator"
    exclusions: list[dict[str, Any]] = []
    for zero_index, reason in sorted(reasons.items()):
        line = lines[zero_index]
        exclusions.append(
            {
                "source_id": anchor_id,
                "source_locator": f"line:{zero_index + 1:04d}",
                "source_sha256": "sha256:"
                + hashlib.sha256(line.encode("utf-8")).hexdigest(),
                "excluded_reason": reason,
            }
        )
    return exclusions


def _prose_source_records(
    segment: str, _builder: Any, anchor_id: str
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_index, line in enumerate(segment.splitlines()[1:]):
        if not line.strip():
            continue
        normalized = _normalize_prose_line(line, anchor_id)
        locator = f"line:{line_index + 2:04d}"
        records.append(
            {
                "source_id": anchor_id,
                "source_locator": locator,
                "source_sha256": "sha256:"
                + hashlib.sha256(line.encode("utf-8")).hexdigest(),
                "source_kind": "prose_line",
                "projections": [],
                "_raw_line": line,
                "_timeline_fallback": normalized,
                "_timeline_event_text": normalized,
                "_other_view_value": {"text": normalized},
            }
        )
    return records


def _project_table_cells(
    anchor_id: str, header: tuple[str, ...], cells: list[str]
) -> list[str]:
    """Preserve source-native order, width, units, masks and decimals exactly."""

    if header not in TABLE_HEADER_VARIANTS.get(anchor_id, ()):
        raise ValueError(f"{anchor_id}未授权表头变体")
    if len(cells) != len(header):
        raise ValueError(
            f"{anchor_id}表格行宽与授权表头不一致:"
            f"expected={len(header)};actual={len(cells)}"
        )
    return list(cells)


def _table_source_records(
    segment: str,
    _builder: Any,
    anchor_id: str,
) -> list[dict[str, Any]]:
    lines = segment.splitlines()
    _, _, header, data_rows, prose_rows = _table_structure(segment, anchor_id)

    table_records = [
        {
            "source_id": anchor_id,
            "source_locator": f"table-row:{row_index + 1:04d}",
            "source_sha256": "sha256:"
            + hashlib.sha256(lines[line_index].encode("utf-8")).hexdigest(),
            "source_kind": "table_row",
            "projections": [],
            "_raw_line": lines[line_index],
            "_timeline_fallback": "，".join(
                f"{header[column]}={cells[column]}"
                for column in range(len(cells))
                if cells[column]
            ),
            "_timeline_event_text": "，".join(
                cell for cell in cells if cell
            ),
            "_other_view_value": {
                "cells": _project_table_cells(anchor_id, header, cells)
            },
        }
        for row_index, (line_index, cells) in enumerate(data_rows)
    ]
    prose_records = [
        {
            "source_id": anchor_id,
            "source_locator": f"line:{line_index + 1:04d}",
            "source_sha256": "sha256:"
            + hashlib.sha256(lines[line_index].encode("utf-8")).hexdigest(),
            "source_kind": "prose_line",
            "projections": [],
            "_raw_line": lines[line_index],
            "_timeline_fallback": normalized,
            "_timeline_event_text": normalized,
            "_other_view_value": {"text": normalized},
        }
        for line_index, normalized in prose_rows
    ]
    return [*table_records, *prose_records]


def _source_date(line: str) -> str | None:
    for date_like in DATE_LIKE_RE.finditer(line):
        if DATE_RE.fullmatch(date_like.group(0)) is None:
            raise ValueError(f"非法日期格式:{date_like.group(0)}")
    matched = DATE_RE.search(line)
    if matched is None:
        return None
    raw = matched.group(0)
    groups = matched.groups()
    parts = groups[:3] if groups[0] is not None else groups[3:]
    try:
        return date(*(int(part) for part in parts)).isoformat()
    except ValueError as exc:
        raise ValueError(f"非法日期:{raw}") from exc


def _timeline_anchor_items(
    segment: str,
    builder: Any,
    anchor_id: str,
    *,
    table_anchor: bool = False,
    defer_table_prose: bool = False,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Consume every eligible A02-A05 source item exactly once.

    A dated prose line or table data row becomes one dated event.  Remaining
    prose items use the existing ``_substantive_lines`` normalization, while
    remaining table data rows use the frozen builder's allowed table summary.
    Titles, table headers and markdown separators are structural rather than
    customer source items and are never emitted.
    """

    records = (
        _table_source_records(segment, builder, anchor_id)
        if table_anchor
        else _prose_source_records(segment, builder, anchor_id)
    )
    events: list[dict[str, Any]] = []
    undated: list[dict[str, Any]] = []

    for record in records:
        if defer_table_prose and record["source_kind"] == "prose_line":
            continue
        locator = record["source_locator"]
        source_date = _source_date(record["_raw_line"])
        if source_date is not None:
            events.append(
                {
                    "date": source_date,
                    "text": record["_timeline_event_text"],
                    "anchor_ids": [anchor_id],
                    "_source_locator": locator,
                    "_event_ordinal": 0,
                }
            )
        else:
            undated.append(
                {
                    "text": record["_timeline_fallback"],
                    "anchor_ids": [anchor_id],
                    "_source_locator": locator,
                }
            )
    return events, undated, records


def _append_source_projection(
    records: dict[tuple[str, str], dict[str, Any]],
    item: dict[str, Any],
    *,
    mode: str,
    slide_id: str,
    slot: str,
    item_index: int,
) -> None:
    source_id = item["anchor_ids"][0]
    locator = item["_source_locator"]
    record = records.get((source_id, locator))
    if record is None:
        raise ValueError(f"未登记源项投影:{source_id}:{locator}")
    projection = {
        "mode": mode,
        "slide_id": slide_id,
        "slot": slot,
        "item_index": item_index,
    }
    locator_key = (slide_id, slot, item_index)
    if any(
        (value["slide_id"], value["slot"], value["item_index"])
        == locator_key
        for value in record["projections"]
    ):
        raise ValueError(f"源项投影重复:{source_id}:{locator}:{locator_key}")
    record["projections"].append(projection)


def _finalize_source_consumption(
    records: list[dict[str, Any]],
    excluded_items: list[dict[str, Any]],
    sections: dict[str, str],
    semantic_inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    semantic_by_location = {
        (item["slide_id"], item["slot"], item["item_index"]): item
        for item in semantic_inventory
    }
    record_keys = [
        (record["source_id"], record["source_locator"]) for record in records
    ]
    if any(count != 1 for count in Counter(record_keys).values()):
        raise ValueError("源消费账定位重复")
    excluded_keys = [
        (item["source_id"], item["source_locator"]) for item in excluded_items
    ]
    if any(count != 1 for count in Counter(excluded_keys).values()):
        raise ValueError("源消费账结构排除项定位重复")
    if set(record_keys).intersection(excluded_keys):
        raise ValueError("源消费账候选项与结构排除项重叠")
    raw_occurrences = Counter(
        (
            anchor_id,
            "sha256:" + hashlib.sha256(line.encode("utf-8")).hexdigest(),
        )
        for anchor_id, segment in sections.items()
        for line in segment.splitlines()
        if line.strip()
    )
    ledger_occurrences = Counter(
        (item["source_id"], item["source_sha256"])
        for item in [*records, *excluded_items]
    )
    if raw_occurrences != ledger_occurrences:
        missing_count = sum((raw_occurrences - ledger_occurrences).values())
        repeated_count = sum((ledger_occurrences - raw_occurrences).values())
        raise ValueError(
            "源消费账与A01-A09原始非空行不等价:"
            f"missing={missing_count};repeated={repeated_count}"
        )
    excluded_anchors = {
        item["source_id"]
        for item in excluded_items
        if item["excluded_reason"] == "anchor_title"
    }
    if excluded_anchors != {f"A{index:02d}" for index in range(1, 10)}:
        raise ValueError("源消费账未完整登记A01-A09标题排除项")

    projection_locations: list[tuple[str, str, int]] = []
    final_items: list[dict[str, Any]] = []
    for record in records:
        projections = record["projections"]
        if not projections:
            raise ValueError(
                "源消费账存在未消费源项:"
                f"{record['source_id']}:{record['source_locator']}"
            )
        final_projections: list[dict[str, Any]] = []
        for projection in projections:
            location = (
                projection["slide_id"],
                projection["slot"],
                projection["item_index"],
            )
            semantic = semantic_by_location.get(location)
            if semantic is None:
                raise ValueError(f"源项投影未绑定语义项:{location}")
            projection_locations.append(location)
            final_projections.append(
                {
                    **projection,
                    "semantic_id": semantic["semantic_id"],
                    "content_sha256": semantic["content_sha256"],
                }
            )
        final_items.append(
            {
                key: value
                for key, value in record.items()
                if not key.startswith("_") and key != "projections"
            }
            | {"projections": final_projections}
        )
    if any(count != 1 for count in Counter(projection_locations).values()):
        raise ValueError("源消费账存在未声明的重复投影")

    candidate_count = len(final_items)
    consumed_count = sum(bool(item["projections"]) for item in final_items)
    if candidate_count == 0 or consumed_count != candidate_count:
        raise ValueError("源消费账覆盖率不足100%")
    return {
        "schema": "source-consumption/1.0",
        "scope": [f"A{index:02d}" for index in range(1, 10)],
        "candidate_item_count": candidate_count,
        "consumed_item_count": consumed_count,
        "total_projection_count": len(projection_locations),
        "coverage_percent": 100,
        "unconsumed_item_count": 0,
        "undeclared_duplicate_count": 0,
        "excluded_item_count": len(excluded_items),
        "excluded_items": excluded_items,
        "items": final_items,
    }


def _profile_value_sha256(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("profile消费账仅接受已校验字符串")
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_value_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    ).hexdigest()


def _profile_targets(
    slides: list[dict[str, Any]],
) -> dict[str, list[tuple[str, str, str, int]]]:
    """Return the exact customer-visible projection stream per profile field."""

    cover = [slide for slide in slides if slide["slide_id"] == "cover-01"]
    final_scope = [slide for slide in slides if slide["slide_id"] == "scope-01"]
    if len(cover) != 1 or len(final_scope) != 1:
        raise ValueError("profile消费账缺少唯一cover-01或scope-01")

    targets: dict[str, list[tuple[str, str, str, int]]] = {
        field: [
            (
                cover[0]["content"]["profile"][field],
                "cover-01",
                f"profile.{field}",
                0,
            )
        ]
        for field in PROFILE_VISIBLE_SCALARS
    }
    targets["executive_summary"] = [
        (value, slide["slide_id"], "items", item_index)
        for slide in slides
        if slide["role"] == "executive_summary"
        for item_index, value in enumerate(slide["content"]["items"])
    ]
    targets["next_steps"] = [
        (value, slide["slide_id"], "items", item_index)
        for slide in slides
        if slide["slide_id"].startswith("next-actions-")
        for item_index, value in enumerate(slide["content"]["items"])
    ]
    targets["scope_items"] = [
        (value, "scope-01", "items", item_index)
        for item_index, value in enumerate(final_scope[0]["content"]["items"])
    ]
    return targets


def _finalize_profile_consumption(
    profile: dict[str, Any],
    slides: list[dict[str, Any]],
    semantic_inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    """Bind each validated profile occurrence to its visible semantic item.

    The denominator is constructed from the validated profile before reading
    the slide projection.  List occurrences use their source index, so equal
    values remain independently accountable.
    """

    source_items: list[dict[str, Any]] = []
    for field in PROFILE_VISIBLE_SCALARS:
        source_items.append(
            {
                "field": field,
                "source_index": 0,
                "source_kind": "scalar",
                "source_sha256": _profile_value_sha256(profile[field]),
                "_value": profile[field],
            }
        )
    for field in PROFILE_VISIBLE_LISTS:
        source_items.extend(
            {
                "field": field,
                "source_index": source_index,
                "source_kind": "list_item",
                "source_sha256": _profile_value_sha256(value),
                "_value": value,
            }
            for source_index, value in enumerate(profile[field])
        )

    semantic_by_location = {
        (item["slide_id"], item["slot"], item["item_index"]): item
        for item in semantic_inventory
    }
    targets = _profile_targets(slides)

    final_items: list[dict[str, Any]] = []
    projection_locations: list[tuple[str, str, int]] = []
    for source_item in source_items:
        field = source_item["field"]
        source_index = source_item["source_index"]
        field_targets = targets.get(field, [])
        if source_index >= len(field_targets):
            raise ValueError(
                f"profile消费账存在未投影项:{field}:{source_index}"
            )
        target_value, slide_id, slot, item_index = field_targets[source_index]
        if target_value != source_item["_value"]:
            raise ValueError(
                f"profile消费账投影值不一致:{field}:{source_index}"
            )
        location = (slide_id, slot, item_index)
        semantic = semantic_by_location.get(location)
        if semantic is None:
            raise ValueError(f"profile消费账未绑定语义项:{location}")
        projection_locations.append(location)
        final_items.append(
            {
                key: value
                for key, value in source_item.items()
                if not key.startswith("_")
            }
            | {
                "projection": {
                    "slide_id": slide_id,
                    "slot": slot,
                    "item_index": item_index,
                    "semantic_id": semantic["semantic_id"],
                    "content_sha256": semantic["content_sha256"],
                }
            }
        )

    for field in (*PROFILE_VISIBLE_SCALARS, *PROFILE_VISIBLE_LISTS):
        expected_count = 1 if field in PROFILE_VISIBLE_SCALARS else len(profile[field])
        if len(targets.get(field, [])) != expected_count:
            raise ValueError(
                f"profile消费账投影数量不一致:{field}:"
                f"expected={expected_count};actual={len(targets.get(field, []))}"
            )
    if any(count != 1 for count in Counter(projection_locations).values()):
        raise ValueError("profile消费账存在重复投影位置")

    excluded_controls = [
        {
            "field": field,
            "source_sha256": _profile_value_sha256(profile[field]),
            "excluded_reason": "non_customer_visible_control",
        }
        for field in PROFILE_CONTROL_FIELDS
    ]
    denominator = [
        {
            "field": item["field"],
            "source_index": item["source_index"],
            "source_sha256": item["source_sha256"],
        }
        for item in final_items
    ]
    denominator_sha256 = "sha256:" + hashlib.sha256(
        (
            json.dumps(
                denominator,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "profile-consumption/1.0",
        "scope": [*PROFILE_VISIBLE_SCALARS, *PROFILE_VISIBLE_LISTS],
        "control_scope": [*PROFILE_CONTROL_FIELDS],
        "candidate_item_count": len(final_items),
        "consumed_item_count": len(final_items),
        "total_projection_count": len(projection_locations),
        "coverage_percent": 100,
        "unconsumed_item_count": 0,
        "undeclared_duplicate_count": 0,
        "denominator_sha256": denominator_sha256,
        "excluded_control_count": len(excluded_controls),
        "excluded_controls": excluded_controls,
        "items": final_items,
    }


def _finalize_derived_consumption(
    records: list[dict[str, Any]],
    semantic_inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    semantic_by_location = {
        (item["slide_id"], item["slot"], item["item_index"]): item
        for item in semantic_inventory
    }
    final_items: list[dict[str, Any]] = []
    locations: list[tuple[str, str, int]] = []
    derived_ids: list[str] = []
    for record in records:
        location = (
            record["slide_id"],
            record["slot"],
            record["item_index"],
        )
        semantic = semantic_by_location.get(location)
        if semantic is None:
            raise ValueError(f"派生消费账未绑定语义项:{location}")
        locations.append(location)
        derived_ids.append(record["derived_id"])
        final_items.append(
            {
                "derived_id": record["derived_id"],
                "derived_reason": record["derived_reason"],
                "value_sha256": _canonical_value_sha256(record["value"]),
                "projection": {
                    "slide_id": location[0],
                    "slot": location[1],
                    "item_index": location[2],
                    "semantic_id": semantic["semantic_id"],
                    "content_sha256": semantic["content_sha256"],
                },
            }
        )
    if len(derived_ids) != len(set(derived_ids)):
        raise ValueError("派生消费账ID重复")
    if len(locations) != len(set(locations)):
        raise ValueError("派生消费账位置重复")
    return {
        "schema": "derived-consumption/1.0",
        "candidate_item_count": len(final_items),
        "consumed_item_count": len(final_items),
        "total_projection_count": len(final_items),
        "coverage_percent": 100,
        "unconsumed_item_count": 0,
        "undeclared_duplicate_count": 0,
        "items": final_items,
    }


def _finalize_domain_projection_partition(
    semantic_inventory: list[dict[str, Any]],
    source_consumption: dict[str, Any],
    profile_consumption: dict[str, Any],
    derived_consumption: dict[str, Any],
) -> dict[str, Any]:
    source_locations = [
        (
            projection["slide_id"],
            projection["slot"],
            projection["item_index"],
        )
        for item in source_consumption["items"]
        for projection in item["projections"]
    ]
    profile_locations = [
        (
            item["projection"]["slide_id"],
            item["projection"]["slot"],
            item["projection"]["item_index"],
        )
        for item in profile_consumption["items"]
    ]
    derived_locations = [
        (
            item["projection"]["slide_id"],
            item["projection"]["slot"],
            item["projection"]["item_index"],
        )
        for item in derived_consumption["items"]
    ]
    all_locations = [*source_locations, *profile_locations, *derived_locations]
    semantic_locations = [
        (item["slide_id"], item["slot"], item["item_index"])
        for item in semantic_inventory
    ]
    overlaps = sum(count - 1 for count in Counter(all_locations).values() if count > 1)
    unpartitioned = sum((Counter(semantic_locations) - Counter(all_locations)).values())
    unexpected = sum((Counter(all_locations) - Counter(semantic_locations)).values())
    if overlaps or unpartitioned or unexpected:
        raise ValueError(
            "语义投影分区未闭合:"
            f"overlap={overlaps};unpartitioned={unpartitioned};unexpected={unexpected}"
        )
    return {
        "schema": "domain-projection-partition/1.0",
        "semantic_item_count": len(semantic_locations),
        "source_projection_count": len(source_locations),
        "profile_projection_count": len(profile_locations),
        "derived_projection_count": len(derived_locations),
        "partitioned_item_count": len(all_locations),
        "overlap_count": 0,
        "unpartitioned_item_count": 0,
        "unexpected_projection_count": 0,
        "semantic_inventory_sha256": _canonical_value_sha256(semantic_inventory),
    }


def _slide(
    *,
    slide_id: str,
    role: str,
    title: str,
    source_refs: Iterable[str],
    content: dict[str, Any],
) -> dict[str, Any]:
    return {
        "slide_id": slide_id,
        "role": role,
        "title": title,
        "source_refs": sorted(set(source_refs)),
        "content": content,
    }


def build_delivery_ir(inputs: dict[str, Any], package_root: Path) -> dict[str, Any]:
    builder = _load_builder(package_root)
    text = inputs["markdown_text"]
    anchors, error = builder.extract_anchors(text)
    if error:
        raise ValueError(f"A01-A09锚提取失败:{error}")
    sections = {
        anchor["anchor_id"]: text[anchor["char_start"] : anchor["char_end"]]
        for anchor in anchors
    }
    source_layout_variant = _resolve_source_layout_variant(sections)
    source_schema = source_schema_for_variant(source_layout_variant)
    profile = inputs["profile"]
    public_profile = {
        "schema": "client-delivery-profile/1.0",
        "client_label": profile["client_label"],
        "matter_label": profile["matter_label"],
        "prepared_by": profile["prepared_by"],
        "materials_as_of": profile["materials_as_of"],
        "confidentiality": profile["confidentiality"],
    }
    cover_profile = {key: value for key, value in public_profile.items() if key != "schema"}
    excluded_source_items = [
        item
        for anchor_id in (f"A{index:02d}" for index in range(1, 10))
        for item in _structural_exclusions(
            sections[anchor_id],
            anchor_id,
            anchor_id in TABLE_HEADER_VARIANTS,
        )
    ]
    source_records: list[dict[str, Any]] = []
    source_records.extend(_table_source_records(sections["A01"], builder, "A01"))
    events: list[dict[str, Any]] = []
    milestones: list[dict[str, Any]] = []
    timeline_source_records: list[dict[str, Any]] = []
    for anchor_id in ("A02", "A03", "A04", "A05"):
        anchor_events, anchor_undated, anchor_records = _timeline_anchor_items(
            sections[anchor_id],
            builder,
            anchor_id,
            table_anchor=anchor_id == "A04",
            defer_table_prose=anchor_id == "A04",
        )
        events.extend(anchor_events)
        milestones.extend(anchor_undated)
        timeline_source_records.extend(anchor_records)
    source_records.extend(timeline_source_records)
    source_records.extend(_table_source_records(sections["A06"], builder, "A06"))
    source_records.extend(_prose_source_records(sections["A07"], builder, "A07"))
    source_records.extend(_table_source_records(sections["A08"], builder, "A08"))
    source_records.extend(_table_source_records(sections["A09"], builder, "A09"))
    source_counts_by_anchor = Counter(
        record["source_id"] for record in source_records
    )
    empty_anchors = [
        f"A{index:02d}"
        for index in range(1, 10)
        if source_counts_by_anchor[f"A{index:02d}"] == 0
    ]
    if empty_anchors:
        raise ValueError(
            "源消费账锚无候选源项:" + ",".join(empty_anchors)
        )
    events.sort(
        key=lambda value: (
            value["date"],
            int(value["anchor_ids"][0][1:]),
            value["_source_locator"],
            value["_event_ordinal"],
        )
    )
    source_records_by_key = {
        (record["source_id"], record["source_locator"]): record
        for record in source_records
    }
    if len(source_records_by_key) != len(source_records):
        raise ValueError("源消费账定位不唯一")
    slides: list[dict[str, Any]] = []
    derived_records: list[dict[str, Any]] = []

    slides.append(
        _slide(
            slide_id="cover-01",
            role="cover",
            title=profile["matter_label"],
            source_refs=[],
            content={
                "profile": cover_profile,
            },
        )
    )
    slides.append(
        _slide(
            slide_id="scope-00",
            role="scope",
            title="阅读须知与使用边界",
            source_refs=[],
            content={
                "items": list(SCOPE_BOUNDARY_ITEMS)
            },
        )
    )
    derived_records.extend(
        {
            "derived_id": f"scope-boundary-{item_index + 1:03d}",
            "derived_reason": "fixed_review_boundary",
            "value": value,
            "slide_id": "scope-00",
            "slot": "items",
            "item_index": item_index,
        }
        for item_index, value in enumerate(SCOPE_BOUNDARY_ITEMS)
    )
    for index, items in enumerate(_balanced_chunks(profile["executive_summary"], 5), 1):
        slides.append(
            _slide(
                slide_id=f"executive-summary-{index:02d}",
                role="executive_summary",
                title="客户沟通摘要" + (f"（续 {index}）" if index > 1 else ""),
                source_refs=[anchor["anchor_id"] for anchor in anchors],
                content={"items": items},
            )
        )

    parties = [
        {
            "text": " / ".join(
                f"{source_schema['table_headers']['A01'][column]}={cell}"
                for column, cell in enumerate(
                    record["_other_view_value"]["cells"]
                )
            ),
            "anchor_ids": ["A01"],
            "_source_locator": record["source_locator"],
        }
        for record in source_records
        if record["source_id"] == "A01"
    ]
    chain = [
        {
            **record["_other_view_value"],
            "anchor_ids": ["A02"],
            "_source_locator": record["source_locator"],
        }
        for record in timeline_source_records
        if record["source_id"] == "A02" and record["source_kind"] == "prose_line"
    ]
    # Party cards and source-bound chain narratives are deliberately separated.
    # Co-locating them made the available chain height depend on party count and
    # encouraged a visually inferred relationship that DeliveryIR v1 does not
    # authorize.  Empty counterpart arrays keep the HTML/PPTX contract exact.
    for index, party_page in enumerate(
        _balanced_chunks(parties, RELATIONSHIP_PARTIES_PER_SLIDE)
        if parties
        else [],
        1,
    ):
        slide_id = f"relationship-parties-{index:02d}"
        for item_index, item in enumerate(party_page):
            _append_source_projection(
                source_records_by_key,
                item,
                mode="other_view",
                slide_id=slide_id,
                slot="parties",
                item_index=item_index,
            )
        slides.append(
            _slide(
                slide_id=slide_id,
                role="relationship",
                title="案件主体" + (f"（续 {index}）" if index > 1 else ""),
                source_refs=["A01"],
                content={
                    "parties": [{"text": item["text"]} for item in party_page],
                    "chain": [],
                },
            )
        )
    for index, chain_page in enumerate(
        _balanced_chunks(chain, RELATIONSHIP_CHAIN_PER_SLIDE)
        if chain
        else [],
        1,
    ):
        slide_id = f"relationship-chain-{index:02d}"
        for item_index, item in enumerate(chain_page):
            _append_source_projection(
                source_records_by_key,
                item,
                mode="other_view",
                slide_id=slide_id,
                slot="chain",
                item_index=item_index,
            )
        slides.append(
            _slide(
                slide_id=slide_id,
                role="relationship",
                title="交易链条" + (f"（续 {index}）" if index > 1 else ""),
                source_refs=["A02"],
                content={
                    "parties": [],
                    "chain": [{"text": item["text"]} for item in chain_page],
                },
            )
        )

    event_pages = (
        _balanced_chunks(events, TIMELINE_EVENTS_PER_SLIDE) if events else []
    )
    timeline_pages = [(event_page, []) for event_page in event_pages]
    if milestones:
        # Real 16pt rows need the full timeline area.  Undated source items are
        # therefore paginated into deterministic trailing pages, never mixed
        # with dated rows or silently truncated by the four-item schema cap.
        timeline_pages.extend(
            ([], milestone_page)
            for milestone_page in _balanced_chunks(
                milestones, TIMELINE_EVENTS_PER_SLIDE
            )
        )
    for index, (event_page, milestone_page) in enumerate(timeline_pages, 1):
        slide_id = f"timeline-{index:02d}"
        for item_index, item in enumerate(event_page):
            _append_source_projection(
                source_records_by_key,
                item,
                mode="dated",
                slide_id=slide_id,
                slot="events",
                item_index=item_index,
            )
        for item_index, item in enumerate(milestone_page):
            _append_source_projection(
                source_records_by_key,
                item,
                mode="undated",
                slide_id=slide_id,
                slot="undated_milestones",
                item_index=item_index,
            )
        slides.append(
            _slide(
                slide_id=slide_id,
                role="timeline",
                title=(
                    "未系日期事项"
                    if not event_page and milestone_page
                    else "关键事件时间线" + (f"（续 {index}）" if index > 1 else "")
                ),
                source_refs=["A02", "A03", "A04", "A05"],
                content={
                    "events": [
                        {"date": item["date"], "text": item["text"]}
                        for item in event_page
                    ],
                    "undated_milestones": [
                        {"text": item["text"]} for item in milestone_page
                    ],
                },
            )
        )

    matrix = [
        {
            "cells": record["_other_view_value"]["cells"],
            "anchor_ids": ["A06"],
            "_source_locator": record["source_locator"],
        }
        for record in source_records
        if record["source_id"] == "A06"
    ]
    amounts = [
        {
            "cells": record["_other_view_value"]["cells"],
            "anchor_ids": ["A04"],
            "_source_locator": record["source_locator"],
        }
        for record in timeline_source_records
        if record["source_id"] == "A04" and record["source_kind"] == "table_row"
    ]
    amount_notes = [
        {
            "text": record["_other_view_value"]["text"],
            "anchor_ids": ["A04"],
            "_source_locator": record["source_locator"],
        }
        for record in timeline_source_records
        if record["source_id"] == "A04" and record["source_kind"] == "prose_line"
    ]
    evidence_index = [
        {
            "text": record["_other_view_value"]["text"],
            "anchor_ids": ["A07"],
            "_source_locator": record["source_locator"],
        }
        for record in source_records
        if record["source_id"] == "A07"
    ]
    matrix_parts = _balanced_chunks(matrix, MATRIX_ROWS_PER_SLIDE) if matrix else []
    amount_parts = _balanced_chunks(amounts, AMOUNTS_PER_SLIDE) if amounts else []
    amount_note_parts = (
        _balanced_chunks(amount_notes, EVIDENCE_PER_SLIDE)
        if amount_notes
        else []
    )
    evidence_parts = (
        _balanced_chunks(evidence_index, EVIDENCE_PER_SLIDE)
        if evidence_index
        else []
    )
    for index, matrix_page in enumerate(matrix_parts):
        slide_id = f"evidence-matrix-{index + 1:02d}"
        for item_index, item in enumerate(matrix_page):
            _append_source_projection(
                source_records_by_key,
                item,
                mode="other_view",
                slide_id=slide_id,
                slot="rows",
                item_index=item_index,
            )
        slides.append(
            _slide(
                slide_id=slide_id,
                role="evidence_matrix",
                title="要件—事实—证据矩阵"
                + (f"（续 {index + 1}）" if index else ""),
                source_refs=["A06"],
                content={
                    "rows": [{"cells": item["cells"]} for item in matrix_page],
                    "amounts": [],
                    "amount_notes": [],
                    "evidence_index": [],
                },
            )
        )
    for index, amount_page in enumerate(amount_parts):
        slide_id = f"evidence-amounts-{index + 1:02d}"
        for item_index, item in enumerate(amount_page):
            _append_source_projection(
                source_records_by_key,
                item,
                mode="other_view",
                slide_id=slide_id,
                slot="amounts",
                item_index=item_index,
            )
        slides.append(
            _slide(
                slide_id=slide_id,
                role="evidence_matrix",
                title="金额口径"
                + (f"（续 {index + 1}）" if index else ""),
                source_refs=["A04"],
                content={
                    "rows": [],
                    "amounts": [{"cells": item["cells"]} for item in amount_page],
                    "amount_notes": [],
                    "evidence_index": [],
                },
            )
        )
    for index, note_page in enumerate(amount_note_parts):
        slide_id = f"evidence-amount-notes-{index + 1:02d}"
        for item_index, item in enumerate(note_page):
            _append_source_projection(
                source_records_by_key,
                item,
                mode="other_view",
                slide_id=slide_id,
                slot="amount_notes",
                item_index=item_index,
            )
        slides.append(
            _slide(
                slide_id=slide_id,
                role="evidence_matrix",
                title="金额口径说明"
                + (f"（续 {index + 1}）" if index else ""),
                source_refs=["A04"],
                content={
                    "rows": [],
                    "amounts": [],
                    "amount_notes": [
                        {"text": item["text"]} for item in note_page
                    ],
                    "evidence_index": [],
                },
            )
        )
    for index, evidence_page in enumerate(evidence_parts):
        slide_id = f"evidence-index-{index + 1:02d}"
        for item_index, item in enumerate(evidence_page):
            _append_source_projection(
                source_records_by_key,
                item,
                mode="other_view",
                slide_id=slide_id,
                slot="evidence_index",
                item_index=item_index,
            )
        slides.append(
            _slide(
                slide_id=slide_id,
                role="evidence_matrix",
                title="证据索引"
                + (f"（续 {index + 1}）" if index else ""),
                source_refs=["A07"],
                content={
                    "rows": [],
                    "amounts": [],
                    "amount_notes": [],
                    "evidence_index": [
                        {"text": item["text"]} for item in evidence_page
                    ],
                },
            )
        )

    stages = [
        {
            "cells": record["_other_view_value"]["cells"],
            "anchor_ids": ["A08"],
            "_source_locator": record["source_locator"],
        }
        for record in source_records
        if record["source_id"] == "A08"
    ]
    risks = [
        {
            "cells": record["_other_view_value"]["cells"],
            "anchor_ids": ["A09"],
            "_source_locator": record["source_locator"],
        }
        for record in source_records
        if record["source_id"] == "A09"
    ]
    if not any("法条" in "".join(item["cells"]) or "法源" in "".join(item["cells"]) for item in risks):
        risks.append(
            {
                "cells": list(LAW_REVIEW_NOTICE_CELLS),
                "anchor_ids": ["A09"],
                "_derived_id": "missing-legal-authority-notice",
                "_derived_reason": "missing_legal_authority_notice",
            }
        )
    for index, stage_page in enumerate(
        _balanced_chunks(stages, STAGES_PER_SLIDE) if stages else [], 1
    ):
        slide_id = f"stage-plan-{index:02d}"
        for item_index, item in enumerate(stage_page):
            _append_source_projection(
                source_records_by_key,
                item,
                mode="other_view",
                slide_id=slide_id,
                slot="stages",
                item_index=item_index,
            )
        slides.append(
            _slide(
                slide_id=slide_id,
                role="stage_risk",
                title="程序阶段计划" + (f"（续 {index}）" if index > 1 else ""),
                source_refs=["A08"],
                content={
                    "stages": [{"cells": item["cells"]} for item in stage_page],
                    "risks": [],
                },
            )
        )
    for index, risk_page in enumerate(
        _balanced_chunks(risks, RISKS_PER_SLIDE) if risks else [], 1
    ):
        slide_id = f"risk-register-{index:02d}"
        for item_index, item in enumerate(risk_page):
            if "_source_locator" in item:
                _append_source_projection(
                    source_records_by_key,
                    item,
                    mode="other_view",
                    slide_id=slide_id,
                    slot="risks",
                    item_index=item_index,
                )
            elif "_derived_id" in item:
                derived_records.append(
                    {
                        "derived_id": item["_derived_id"],
                        "derived_reason": item["_derived_reason"],
                        "value": {"cells": item["cells"]},
                        "slide_id": slide_id,
                        "slot": "risks",
                        "item_index": item_index,
                    }
                )
        slides.append(
            _slide(
                slide_id=slide_id,
                role="stage_risk",
                title="风险与暂停事项" + (f"（续 {index}）" if index > 1 else ""),
                source_refs=["A09"],
                content={
                    "stages": [],
                    "risks": [{"cells": item["cells"]} for item in risk_page],
                },
            )
        )

    gaps = []
    for row in matrix:
        cells = row["cells"]
        if source_layout_variant == "canonical-v1":
            has_gap = len(cells) == 5 and (
                (cells[3] and cells[3] not in {"无", "-", "—"})
                or "待" in cells[4]
                or "缺" in cells[4]
            )
        elif source_layout_variant == "legacy-frozen07-v1":
            # Legacy column four is 状态 and column five is only 备注.  A
            # remark is not itself an evidence gap; only an explicit 待/缺
            # state creates the second source projection.
            has_gap = len(cells) == 5 and (
                "待" in cells[3] or "缺" in cells[3]
            )
        else:  # guarded above, retained as a local fail-closed invariant
            raise ValueError(f"未知A06布局变体:{source_layout_variant}")
        if has_gap:
            gaps.append(
                {
                    "text": "；".join(cells),
                    "anchor_ids": ["A06"],
                    "_source_locator": row["_source_locator"],
                }
            )
    for index, items in enumerate(
        _balanced_chunks(profile["next_steps"], NEXT_STEPS_PER_SLIDE), 1
    ):
        slides.append(
            _slide(
                slide_id=f"next-actions-{index:02d}",
                role="next_steps",
                title="下一步行动" + (f"（续 {index}）" if index > 1 else ""),
                source_refs=["A08", "A09"],
                content={"items": items, "gaps": []},
            )
        )
    for index, gap_page in enumerate(
        _balanced_chunks(gaps, GAPS_PER_SLIDE) if gaps else [], 1
    ):
        slide_id = f"evidence-gaps-{index:02d}"
        for item_index, item in enumerate(gap_page):
            _append_source_projection(
                source_records_by_key,
                item,
                mode="other_view",
                slide_id=slide_id,
                slot="gaps",
                item_index=item_index,
            )
        slides.append(
            _slide(
                slide_id=slide_id,
                role="next_steps",
                title="待核与证据缺口" + (f"（续 {index}）" if index > 1 else ""),
                source_refs=["A06"],
                content={"items": [], "gaps": [item["text"] for item in gap_page]},
            )
        )

    slides.append(
        _slide(
            slide_id="scope-01",
            role="scope",
            title="证据范围与放行边界",
            source_refs=[anchor["anchor_id"] for anchor in anchors],
            content={"items": profile["scope_items"]},
        )
    )

    used_sources = {source for slide in slides for source in slide["source_refs"]}
    expected_sources = {f"A{index:02d}" for index in range(1, 10)}
    if used_sources != expected_sources:
        raise ValueError("DeliveryIR未完整使用A01-A09")
    sources = [
        {
            "source_id": anchor["anchor_id"],
            "sha256": f"sha256:{anchor['sha256']}",
            "data_class": profile["data_class"],
            "frozen": True,
        }
        for anchor in anchors
    ]
    delivery_ir = {
        "schema": "delivery-ir/1.0",
        "source_schema": source_schema,
        "case_ref": profile["case_ref"],
        "data_class": profile["data_class"],
        "release_state": "REVIEW_DRAFT",
        "input_sha256": f"sha256:{inputs['input_sha256']}",
        "profile_sha256": f"sha256:{inputs['profile_sha256']}",
        "profile": public_profile,
        "sources": sources,
        "slides": slides,
    }
    derived_records.extend(
        {
            "derived_id": f"slide-title:{slide['slide_id']}",
            "derived_reason": "closed_slide_title",
            "value": slide["title"],
            "slide_id": slide["slide_id"],
            "slot": "title",
            "item_index": 0,
        }
        for slide in slides
    )
    semantic_inventory = build_source_inventory(slides)
    delivery_ir["semantic_inventory"] = semantic_inventory
    profile_consumption = _finalize_profile_consumption(
        profile, slides, semantic_inventory
    )
    source_consumption = _finalize_source_consumption(
        source_records, excluded_source_items, sections, semantic_inventory
    )
    derived_consumption = _finalize_derived_consumption(
        derived_records, semantic_inventory
    )
    delivery_ir["profile_consumption"] = profile_consumption
    delivery_ir["source_consumption"] = source_consumption
    delivery_ir["derived_consumption"] = derived_consumption
    delivery_ir["domain_projection_partition"] = (
        _finalize_domain_projection_partition(
            semantic_inventory,
            source_consumption,
            profile_consumption,
            derived_consumption,
        )
    )
    return delivery_ir
