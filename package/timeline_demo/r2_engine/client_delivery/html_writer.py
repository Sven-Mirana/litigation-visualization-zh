"""Deterministic, offline-only HTML writer for the S2 client delivery IR.

This module deliberately has no template engine or browser dependency.  It
renders only the closed, customer-visible field allowlist for the eight S2
slide roles.  Governance sidecars and unknown fields never enter the HTML.
"""

from __future__ import annotations

import copy
from datetime import date
import hashlib
import html
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable, Mapping, Sequence

try:
    from .delivery_ir import visible_table_headers
    from .semantic_inventory import require_source_inventory
except ImportError:  # direct-file unit loading
    from client_delivery.delivery_ir import visible_table_headers
    from client_delivery.semantic_inventory import require_source_inventory


_ROLES = {
    "cover",
    "executive_summary",
    "relationship",
    "timeline",
    "evidence_matrix",
    "stage_risk",
    "next_steps",
    "scope",
}

_ROLE_LABELS = {
    "cover": "案件概览",
    "executive_summary": "执行摘要",
    "relationship": "主体关系",
    "timeline": "关键时间线",
    "evidence_matrix": "要件与证据",
    "stage_risk": "阶段与风险",
    "next_steps": "缺口与下一步",
    "scope": "范围与说明",
}

_PROFILE_FIELDS = (
    ("client_label", "客户"),
    ("matter_label", "项目"),
    ("case_ref", "案件编号"),
    ("version", "版本"),
    ("materials_as_of", "材料截止日"),
    ("prepared_by", "编制"),
    ("confidentiality", "保密级别"),
)

_PROFILE_ALIASES = {
    "client_label": ("client_name",),
    "matter_label": ("matter_name", "case_name"),
    "materials_as_of": ("as_of_date",),
}

_DISPLAY_REVIEW_STATE = "审阅稿"
_DISPLAY_CONFIDENTIALITY = {
    "CONFIDENTIAL": "机密",
    "ATTORNEY_WORK_PRODUCT": "律师工作成果",
    "INTERNAL_REVIEW_ONLY": "仅供内部审阅",
}
_DISPLAY_DOCUMENT_LABEL = "诉讼可视化"
_TIMELINE_PROFILES = {"a", "b"}

_PII_CANARY = re.compile(
    r"(?:pii|privacy|secret)[_-]?canary|canary[_-]?(?:pii|privacy|secret)",
    re.IGNORECASE,
)


class HtmlRenderError(ValueError):
    """Raised before committing an HTML artifact when the IR is not closed."""


def _display_confidentiality(value: Any) -> str:
    if not isinstance(value, str) or value not in _DISPLAY_CONFIDENTIALITY:
        raise HtmlRenderError("confidentiality缺少简体中文显示映射")
    return _DISPLAY_CONFIDENTIALITY[value]


def _visible_text(value: Any) -> str:
    if isinstance(value, Mapping):
        if isinstance(value.get("cells"), (list, tuple)):
            return "".join(str(cell) for cell in value["cells"])
        if isinstance(value.get("date"), str) and isinstance(value.get("text"), str):
            return value["date"] + value["text"]
        value = value.get("text")
    if not isinstance(value, str):
        raise HtmlRenderError("visible text hash requires a closed text value")
    return value.strip()


def _visible_hash_attr(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f' data-visible-text-sha256="sha256:{digest}"'


def _semantic_id_attr(semantic_id: str, text: str) -> str:
    return (
        f' data-semantic-id="{html.escape(semantic_id, quote=True)}"'
        + _visible_hash_attr(text)
    )


def _semantic_attr(value: Any, visible_text: str | None = None) -> str:
    if not isinstance(value, Mapping):
        return ""
    semantic_id = value.get("_semantic_id")
    if not isinstance(semantic_id, str):
        return ""
    return _semantic_id_attr(
        semantic_id, visible_text if visible_text is not None else _visible_text(value)
    )


def _static_attr(static_id: str, text: str) -> str:
    return (
        f' data-static-id="{html.escape(static_id, quote=True)}"'
        + _visible_hash_attr(text)
    )


_OWNER_ATTR_RE = re.compile(
    r' data-(semantic|static)-id="([^"]+)"'
    r' data-visible-text-sha256="(sha256:[0-9a-f]{64})"'
)


def _article_owner_receipt(inner_html: str) -> str:
    owners = [list(match) for match in _OWNER_ATTR_RE.findall(inner_html)]
    if not owners:
        raise HtmlRenderError("article visible-owner ledger is empty")
    payload = json.dumps(
        owners, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return (
        f' data-visible-owner-count="{len(owners)}"'
        f' data-visible-owner-ledger-sha256="sha256:{digest}"'
    )


def _annotate_semantics(delivery_ir: Mapping[str, Any]) -> dict[str, Any]:
    """Attach validated semantic IDs to a private render copy, never the source IR."""

    annotated = copy.deepcopy(dict(delivery_ir))
    slides = annotated.get("slides")
    if not isinstance(slides, list):
        raise HtmlRenderError("slides must be an array")
    by_slide = {
        slide.get("slide_id"): slide
        for slide in slides
        if isinstance(slide, Mapping) and isinstance(slide.get("slide_id"), str)
    }
    try:
        inventory = require_source_inventory(delivery_ir)
    except ValueError as exc:
        raise HtmlRenderError(str(exc)) from exc
    for item in inventory:
        slide = by_slide.get(item["slide_id"])
        if not isinstance(slide, dict):
            raise HtmlRenderError(f'semantic slide missing:{item["slide_id"]}')
        content = slide.get("content")
        if not isinstance(content, dict):
            raise HtmlRenderError("semantic slide content must be an object")
        slot = item["slot"]
        if slot == "title":
            if "_semantic_title_id" in content:
                raise HtmlRenderError(f'duplicate semantic title:{item["slide_id"]}')
            content["_semantic_title_id"] = item["semantic_id"]
            continue
        if slot.startswith("profile."):
            key = slot.split(".", 1)[1]
            ids = content.setdefault("_semantic_profile_ids", {})
            if not isinstance(ids, dict) or key in ids:
                raise HtmlRenderError(f"duplicate semantic cover field:{key}")
            ids[key] = item["semantic_id"]
            continue
        values = content.get(slot)
        index = item["item_index"]
        if not isinstance(values, list) or index >= len(values):
            raise HtmlRenderError(f"semantic locator missing:{item['slide_id']}/{slot}/{index}")
        value = values[index]
        if isinstance(value, dict):
            if "_semantic_id" in value:
                raise HtmlRenderError("semantic annotation collision")
            value["_semantic_id"] = item["semantic_id"]
        else:
            values[index] = {"text": value, "_semantic_id": item["semantic_id"]}
    return annotated


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HtmlRenderError(f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, (list, tuple)):
        raise HtmlRenderError(f"{label} must be an array")
    return value


def _text(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if isinstance(value, Mapping):
        value = value.get("text")
    if not isinstance(value, str):
        raise HtmlRenderError(f"{label} must be text or an object with text")
    value = value.strip()
    if not value and not allow_empty:
        raise HtmlRenderError(f"{label} must not be empty")
    return value


def _escaped(value: Any, label: str, *, allow_empty: bool = False) -> str:
    """Escape customer text and make URL-looking text inert in raw markup.

    URLs remain readable to a human, but the colon is represented as an HTML
    entity.  More importantly, user text is never emitted into an attribute,
    link, style block, SVG node or any other fetch-capable location.
    """

    escaped = html.escape(_text(value, label, allow_empty=allow_empty), quote=True)
    return re.sub(r"(?i)\b(https?|file)://", r"\1&#58;//", escaped)


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_strings(item)


def _reject_pii_canary(delivery_ir: Mapping[str, Any]) -> None:
    if any(_PII_CANARY.search(value) for value in _iter_strings(delivery_ir)):
        raise HtmlRenderError("PII canary detected; refusing client artifact")


def _item_list(items: Any, label: str, *, ordered: bool = False) -> str:
    values = _sequence(items, label)
    tag = "ol" if ordered else "ul"
    rendered = "".join(
        f'<li{_semantic_attr(item)}>{_escaped(item, f"{label}[{index}]")}</li>'
        for index, item in enumerate(values)
    )
    return f'<{tag} class="item-list">{rendered}</{tag}>'


def _table(rows: Any, label: str) -> str:
    values = _sequence(rows, label)
    if not values:
        empty = "本节暂无已确认条目。"
        return f'<p class="empty-state"{_static_attr(f"{label}:empty", empty)}>{empty}</p>'
    rendered_rows: list[str] = []
    expected_width: int | None = None
    for row_index, row in enumerate(values):
        row_map = _mapping(row, f"{label}[{row_index}]")
        cells = _sequence(row_map.get("cells"), f"{label}[{row_index}].cells")
        if not cells:
            raise HtmlRenderError(f"{label}[{row_index}].cells must not be empty")
        if expected_width is None:
            expected_width = len(cells)
        elif len(cells) != expected_width:
            raise HtmlRenderError(f"{label} has inconsistent row widths")
        cell_tag = "th" if row_index == 0 else "td"
        rendered_cells = "".join(
            f"<{cell_tag}>{_escaped(cell, f'{label}[{row_index}].cells[{cell_index}]')}</{cell_tag}>"
            for cell_index, cell in enumerate(cells)
        )
        visible_text = "".join(_text(cell, f"{label}[{row_index}]") for cell in cells)
        row_attr = _semantic_attr(row_map, visible_text)
        if not row_attr:
            row_attr = _static_attr(f"{label}:header", visible_text)
        rendered_rows.append(f"<tr{row_attr}>{rendered_cells}</tr>")
    head = rendered_rows[0]
    body = "".join(rendered_rows[1:])
    return (
        '<div class="table-wrap"><table><thead>'
        f"{head}</thead><tbody>{body}</tbody></table></div>"
    )


def _table_with_header(rows: Any, label: str, header: list[str]) -> str:
    values = list(_sequence(rows, label))
    if not values:
        return _table(values, label)
    first = _mapping(values[0], f"{label}[0]")
    first_cells = list(_sequence(first.get("cells"), f"{label}[0].cells"))
    if len(first_cells) == len(header) and first_cells != header:
        values = [{"cells": header}, *values]
    return _table(values, label)


def _cards(items: Any, label: str) -> str:
    values = _sequence(items, label)
    rendered = "".join(
        f'<div class="card"{_semantic_attr(item)}><span class="card-dot"></span>'
        f'<span>{_escaped(item, f"{label}[{index}]")}</span></div>'
        for index, item in enumerate(values)
    )
    return f'<div class="card-grid">{rendered}</div>'


def _render_cover(
    content: Mapping[str, Any], profile: Mapping[str, Any], slide_title: str
) -> str:
    content_profile = content.get("profile", content)
    if not isinstance(content_profile, Mapping):
        raise HtmlRenderError("cover.content.profile must be an object")
    merged = dict(profile)
    profile_keys = set(dict(_PROFILE_FIELDS))
    profile_keys.update(alias for values in _PROFILE_ALIASES.values() for alias in values)
    profile_keys.update({"title", "document_title", "subtitle"})
    for key in profile_keys:
        if key in content_profile:
            merged[key] = content_profile[key]

    def profile_value(key: str) -> Any:
        value = merged.get(key)
        if value is not None and value != "":
            return value
        for alias in _PROFILE_ALIASES.get(key, ()):
            value = merged.get(alias)
            if value is not None and value != "":
                return value
        return None

    semantic_profile_ids = content.get("_semantic_profile_ids", {})
    if not isinstance(semantic_profile_ids, Mapping):
        raise HtmlRenderError("cover semantic profile ids must be an object")

    def profile_attr(key: str, value: str) -> str:
        semantic_id = semantic_profile_ids.get(key)
        if not isinstance(semantic_id, str):
            raise HtmlRenderError(f"cover semantic id missing:{key}")
        return _semantic_id_attr(semantic_id, value)

    title_value = slide_title
    matter_value = profile_value("matter_label") or "诉讼案件可视化报告"
    if title_value != matter_value:
        raise HtmlRenderError("cover title must equal the closed matter label")
    subtitle_value = profile_value("client_label") or "客户沟通材料"
    title_semantic_id = content.get("_semantic_title_id")
    if not isinstance(title_semantic_id, str):
        raise HtmlRenderError("cover semantic title id missing")
    title_attr = _semantic_id_attr(title_semantic_id, title_value)
    metadata: list[str] = []
    for key, label in _PROFILE_FIELDS:
        if key in {"client_label", "matter_label"}:
            continue
        value = profile_value(key)
        if value is None or value == "":
            continue
        display_value = (
            _display_confidentiality(value) if key == "confidentiality" else str(value)
        )
        semantic_attr = (
            profile_attr(key, display_value)
            if key in semantic_profile_ids
            else ""
        )
        if not semantic_attr:
            semantic_attr = _static_attr(f"cover-meta-value:{key}", display_value)
        label_attr = _static_attr(f"cover-meta-label:{key}", label)
        metadata.append(
            f'<div class="meta-row"><dt{label_attr}>'
            f'{html.escape(label)}</dt><dd{semantic_attr}>{_escaped(display_value, f"profile.{key}")}</dd></div>'
        )
    lead = "基于已冻结材料整理，用于律师与客户共同复核事实、证据和下一步安排。"
    return (
        '<div class="cover-layout">'
        '<div class="cover-copy">'
        '<svg class="brand-mark" viewBox="0 0 96 96" role="img" aria-label="诉讼可视化">'
        '<rect x="7" y="7" width="82" height="82" rx="22"></rect>'
        '<path d="M27 62h42M32 38h32M39 27v35M57 27v35"></path>'
        '</svg>'
        f'<h1{title_attr}><span{profile_attr("matter_label", title_value)}>'
        f'{_escaped(title_value, "profile.title")}</span></h1>'
        f'<p class="eyebrow"{profile_attr("client_label", subtitle_value)}>{_escaped(subtitle_value, "profile.subtitle")}</p>'
        f'<p class="lead"{_static_attr("cover-lead", lead)}>{lead}</p>'
        '</div>'
        f'<dl class="cover-meta">{"".join(metadata)}</dl>'
        '</div>'
    )


def _render_summary(content: Mapping[str, Any]) -> str:
    return _item_list(content.get("items", []), "executive_summary.items")


def _render_relationship(content: Mapping[str, Any]) -> str:
    sections: list[str] = []
    if content.get("parties"):
        parties = _cards(content["parties"], "relationship.parties")
        heading = "相关主体"
        sections.append(f'<section class="content-block"><h3{_static_attr("relationship:parties-heading", heading)}>{heading}</h3>{parties}</section>')
    if content.get("chain"):
        # Preserve source order without adding a visible ordinal that could be
        # mistaken for a legal or temporal relationship assertion.
        chain = _item_list(content["chain"], "relationship.chain")
        heading = "关系链条"
        sections.append(f'<section class="content-block"><h3{_static_attr("relationship:chain-heading", heading)}>{heading}</h3>{chain}</section>')
    return "".join(sections)


def _timeline_position_percentages(events: Sequence[Any]) -> list[float]:
    """Return a bounded, date-proportional scale without changing source order."""

    if not events:
        return []
    parsed: list[date] = []
    for index, event in enumerate(events):
        item = _mapping(event, f"timeline.events[{index}]")
        value = _text(item.get("date"), f"timeline.events[{index}].date")
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError as exc:
            raise HtmlRenderError(f"timeline.events[{index}].date is not ISO date") from exc
        if parsed_date.isoformat() != value:
            raise HtmlRenderError(f"timeline.events[{index}].date is not canonical ISO date")
        parsed.append(parsed_date)
    if parsed != sorted(parsed):
        raise HtmlRenderError("timeline event date order drifted")
    if len(parsed) == 1:
        return [50.0]
    span = (parsed[-1] - parsed[0]).days
    if span <= 0:
        raise HtmlRenderError("timeline date scale is degenerate")
    return [14.0 + 72.0 * (value - parsed[0]).days / span for value in parsed]


def _render_timeline(
    content: Mapping[str, Any], timeline_profile: str | None = None
) -> str:
    events = _sequence(content.get("events", []), "timeline.events")
    positions = (
        _timeline_position_percentages(events)
        if timeline_profile in {"a", "b"}
        else []
    )
    event_html: list[str] = []
    for index, event in enumerate(events):
        item = _mapping(event, f"timeline.events[{index}]")
        date_html = _escaped(item.get("date"), f"timeline.events[{index}].date")
        text_html = _escaped(item.get("text"), f"timeline.events[{index}].text")
        owner = _semantic_attr(item)
        if timeline_profile == "a":
            event_html.append(
                f'<li class="timeline-event axis-event" style="--timeline-position:{positions[index]:.4f}%"{owner}>'
                f'<div class="axis-label"><time>{date_html}</time><p>{text_html}</p></div></li>'
            )
        elif timeline_profile == "b":
            event_html.append(
                f'<li class="timeline-event docket-row" style="--timeline-position:{positions[index]:.4f}%"{owner}><time>{date_html}</time>'
                f'<p>{text_html}</p></li>'
            )
        else:
            event_html.append(
                f'<li class="timeline-event"{owner}><time>{date_html}</time>'
                f'<p>{text_html}</p></li>'
            )
    undated = content.get("undated_milestones", [])
    undated_section = ""
    if undated:
        undated_html = _item_list(undated, "timeline.undated_milestones")
        heading = "未定日期里程碑"
        undated_section = (
            f'<section class="content-block compact"><h3{_static_attr("timeline:undated-heading", heading)}>{heading}</h3>'
            f'{undated_html}</section>'
        )
    composition = {
        "a": "horizon-axis",
        "b": "docket-register",
        None: "legacy-rail-card",
    }[timeline_profile]
    return f'<ol class="timeline {composition}">{"".join(event_html)}</ol>{undated_section}'


def _render_evidence_matrix(
    content: Mapping[str, Any], table_headers: Mapping[str, list[str]]
) -> str:
    sections: list[str] = []
    if content.get("rows"):
        heading = "要件—证据矩阵"
        sections.append(
            f'<section class="content-block"><h3{_static_attr("evidence:matrix-heading", heading)}>{heading}</h3>'
            f'{_table_with_header(content["rows"], "evidence_matrix.rows", table_headers["matrix"])}</section>'
        )
    supporting: list[str] = []
    if content.get("amounts"):
        heading = "金额事项"
        supporting.append(
            f'<section class="content-block"><h3{_static_attr("evidence:amounts-heading", heading)}>{heading}</h3>'
            f'{_table_with_header(content["amounts"], "evidence_matrix.amounts", table_headers["amounts"])}</section>'
        )
    if content.get("amount_notes"):
        heading = "金额口径说明"
        supporting.append(
            f'<section class="content-block"><h3{_static_attr("evidence:amount-notes-heading", heading)}>{heading}</h3>'
            f'{_item_list(content["amount_notes"], "evidence_matrix.amount_notes")}</section>'
        )
    if content.get("evidence_index"):
        heading = "证据索引"
        supporting.append(
            f'<section class="content-block"><h3{_static_attr("evidence:index-heading", heading)}>{heading}</h3>'
            f'{_item_list(content["evidence_index"], "evidence_matrix.evidence_index")}</section>'
        )
    if supporting:
        sections.append(f'<div class="split">{"".join(supporting)}</div>')
    return "".join(sections)


def _render_stage_risk(
    content: Mapping[str, Any], table_headers: Mapping[str, list[str]]
) -> str:
    sections: list[str] = []
    if content.get("stages"):
        heading = "程序阶段"
        sections.append(
            f'<section class="content-block"><h3{_static_attr("stage-risk:stages-heading", heading)}>{heading}</h3>'
            f'{_table_with_header(content["stages"], "stage_risk.stages", table_headers["stages"])}</section>'
        )
    if content.get("risks"):
        heading = "风险事项"
        sections.append(
            f'<section class="content-block"><h3{_static_attr("stage-risk:risks-heading", heading)}>{heading}</h3>'
            f'{_table_with_header(content["risks"], "stage_risk.risks", table_headers["risks"])}</section>'
        )
    return "".join(sections)


def _render_next_steps(content: Mapping[str, Any]) -> str:
    sections: list[str] = []
    if content.get("items"):
        heading = "下一步行动"
        sections.append(
            f'<section class="content-block"><h3{_static_attr("next-steps:items-heading", heading)}>{heading}</h3>'
            f'{_item_list(content["items"], "next_steps.items", ordered=True)}</section>'
        )
    if content.get("gaps"):
        heading = "待补证据或信息"
        sections.append(
            f'<section class="content-block"><h3{_static_attr("next-steps:gaps-heading", heading)}>{heading}</h3>'
            f'{_item_list(content["gaps"], "next_steps.gaps")}</section>'
        )
    return f'<div class="split">{"".join(sections)}</div>' if sections else ""


def _render_scope(content: Mapping[str, Any]) -> str:
    boundary = content.get("boundary")
    if boundary is None:
        boundary_value = "本报告仅反映当前材料范围和复核状态，不替代律师对事实、法律与策略的最终判断。"
    else:
        boundary_value = _text(boundary, "scope.boundary")
    boundary_html = _escaped(boundary_value, "scope.boundary")
    materials_as_of = content.get("materials_as_of")
    cutoff_html = ""
    if materials_as_of is not None:
        cutoff_value = "材料截止日：" + _text(materials_as_of, "scope.materials_as_of")
        cutoff_html = (
            f'<p class="scope-cutoff"{_static_attr("scope:cutoff", cutoff_value)}>'
            '<strong>材料截止日：</strong>'
            f'{_escaped(materials_as_of, "scope.materials_as_of")}</p>'
        )
    return (
        f'<div class="scope-note"{_static_attr("scope:boundary", boundary_value)}>{boundary_html}</div>{cutoff_html}'
        f'{_item_list(content.get("items", []), "scope.items")}'
    )


_RENDERERS = {
    "cover": _render_cover,
    "executive_summary": _render_summary,
    "relationship": _render_relationship,
    "timeline": _render_timeline,
    "evidence_matrix": _render_evidence_matrix,
    "stage_risk": _render_stage_risk,
    "next_steps": _render_next_steps,
    "scope": _render_scope,
}


def _watermark(release_state: Any) -> str:
    if isinstance(release_state, Mapping):
        release_state = release_state.get("status")
    if not isinstance(release_state, str):
        raise HtmlRenderError("release_state must be REVIEW_DRAFT")
    normalized = release_state.strip().upper().replace("-", "_").replace(" ", "_")
    if normalized != "REVIEW_DRAFT":
        raise HtmlRenderError(
            "HTML writer is REVIEW_DRAFT-only; CLIENT_READY requires a separately reviewed human release-receipt path"
        )
    return _DISPLAY_REVIEW_STATE


def _source_footer(refs: Any, label: str) -> str:
    values = _sequence(refs, label)
    if not values:
        return ""
    rendered = " · ".join(
        _escaped(value, f"{label}[{index}]") for index, value in enumerate(values)
    )
    visible = "来源索引：" + " · ".join(_text(value, label) for value in values)
    return f'<p class="source-refs"{_static_attr("footer:source-refs", visible)}>来源索引：{rendered}</p>'


def _render_slide(
    slide: Any,
    index: int,
    profile: Mapping[str, Any],
    watermark: str,
    table_headers: Mapping[str, list[str]],
    timeline_profile: str | None = None,
) -> str:
    item = _mapping(slide, f"slides[{index}]")
    role = item.get("role")
    if not isinstance(role, str) or role not in _ROLES:
        raise HtmlRenderError(f"slides[{index}].role is not an allowed role")
    content = _mapping(item.get("content", {}), f"slides[{index}].content")
    renderer = _RENDERERS[role]
    title = item.get("title") or _ROLE_LABELS[role]
    if role == "cover":
        body = renderer(content, profile, title)
    elif role in {"evidence_matrix", "stage_risk"}:
        body = renderer(content, table_headers)
    elif role == "timeline":
        body = renderer(content, timeline_profile)
    else:
        body = renderer(content)

    slide_id = item.get("slide_id") or f"S{index + 1:02d}"
    title_semantic_id = content.get("_semantic_title_id")
    if not isinstance(title_semantic_id, str):
        raise HtmlRenderError(f"slide semantic title id missing:{slide_id}")
    title_attr = _semantic_id_attr(title_semantic_id, str(title))
    role_label = _ROLE_LABELS[role]
    header = "" if role == "cover" else (
        '<header class="slide-header">'
        f'<p class="eyebrow"{_static_attr("header:role-label", role_label)}>{html.escape(role_label)}</p>'
        f'<h2{title_attr}>{_escaped(title, f"slides[{index}].title")}</h2></header>'
    )
    footer = _source_footer(item.get("source_refs", []), f"slides[{index}].source_refs")
    page_text = f"{index + 1:02d}"
    document_label = _DISPLAY_DOCUMENT_LABEL
    inner = (
        f'<div class="watermark"{_static_attr("watermark:release-state", watermark)}>{html.escape(watermark)}</div>'
        f'{header}<div class="slide-body">{body}</div>'
        '<footer class="slide-footer">'
        f'<span{_static_attr("footer:document-label", document_label)}>{document_label}</span>'
        f'{footer}<span{_static_attr("footer:page-number", page_text)}>{page_text}</span></footer>'
    )
    return (
        f'<article class="slide role-{role}"{_article_owner_receipt(inner)}>'
        f'{inner}</article>'
    )


_CSS = r"""
:root {
  color-scheme: light;
  --ink: #182234;
  --muted: #667085;
  --line: #d9dee8;
  --paper: #ffffff;
  --canvas: #eef1f5;
  --accent: #233d66;
  --accent-soft: #e8eef7;
  --warm: #a36b2c;
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--canvas); color: var(--ink); }
body { padding: 32px 0; }
.deck { display: grid; gap: 28px; justify-content: center; }
.slide {
  position: relative;
  width: min(1280px, calc(100vw - 32px));
  aspect-ratio: 16 / 9;
  min-height: 720px;
  padding: 52px 66px 40px;
  overflow: visible;
  background: var(--paper);
  border: 1px solid var(--line);
  box-shadow: 0 18px 48px rgba(24, 34, 52, .12);
  display: grid;
  grid-template-rows: auto 1fr auto;
}
.watermark {
  position: absolute;
  top: 20px;
  right: 22px;
  padding: 7px 12px;
  border: 1px dashed #a8b0bd;
  border-radius: 999px;
  color: #7a8493;
  background: #f7f8fa;
  font: 700 12px/1 "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
  letter-spacing: .12em;
  white-space: nowrap;
}
.slide-header { border-bottom: 2px solid var(--accent); padding-bottom: 14px; margin-bottom: 22px; }
.slide-header > .eyebrow { white-space: nowrap; }
.eyebrow { margin: 0 0 9px; color: var(--accent); font-size: 14px; font-weight: 700; letter-spacing: .16em; }
h1, h2, h3, p { margin-top: 0; }
h1 { max-width: 820px; margin-bottom: 20px; font-size: clamp(42px, 5vw, 70px); line-height: 1.12; letter-spacing: -.03em; }
h2 { margin-bottom: 0; font-size: 34px; line-height: 1.2; }
h3 { margin-bottom: 12px; font-size: 18px; color: var(--accent); }
p, li, td, th, dd, dt { font-size: 17px; line-height: 1.55; }
.lead { max-width: 760px; color: var(--muted); font-size: 20px; }
.slide-body { min-height: 0; }
.slide-footer { align-self: end; display: grid; grid-template-columns: 1fr auto auto; gap: 22px; align-items: end; border-top: 1px solid var(--line); padding-top: 10px; color: var(--muted); font-size: 12px; }
.slide-footer > [data-static-id="footer:document-label"] { white-space: nowrap; }
.source-refs { margin: 0; max-width: 620px; text-align: right; font-size: 12px; }
.cover-layout { height: 100%; display: grid; grid-template-columns: 1.65fr .85fr; gap: 64px; align-items: center; }
.brand-mark { width: 74px; height: 74px; margin-bottom: 30px; fill: var(--accent-soft); stroke: var(--accent); stroke-width: 4; stroke-linecap: round; }
.cover-meta { margin: 0; padding: 26px; border: 1px solid var(--line); border-top: 5px solid var(--accent); background: #fafbfc; }
.meta-row { display: grid; grid-template-columns: 96px 1fr; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--line); }
.meta-row:last-child { border-bottom: 0; }
.meta-row dt { color: var(--muted); white-space: nowrap; }
.meta-row dd { margin: 0; font-weight: 650; }
.item-list { margin: 0; padding-left: 1.35em; display: grid; gap: 13px; }
.item-list li::marker { color: var(--warm); font-weight: 700; }
.content-block { margin-bottom: 24px; }
.content-block.compact { margin-top: 22px; }
.split { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; }
.card-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.card { min-height: 74px; padding: 17px; border: 1px solid var(--line); border-radius: 12px; background: #fbfcfe; display: flex; gap: 11px; align-items: center; }
.card-dot { width: 9px; height: 9px; flex: none; border-radius: 50%; background: var(--accent); }
.timeline { list-style: none; margin: 0; padding: 0 0 0 24px; border-left: 2px solid var(--accent); display: grid; gap: 15px; }
.timeline-event { position: relative; padding: 14px 18px; border: 1px solid #c5d1e2; border-radius: 14px; background: #f4f7fa; display: grid; grid-template-columns: 128px 1fr; gap: 20px; }
.timeline-event::before { content: ""; position: absolute; left: -39px; top: 22px; width: 12px; height: 12px; border: 3px solid var(--accent); border-radius: 50%; background: white; }
.timeline-event time { font-weight: 700; color: var(--accent); }
.timeline-event p { margin-bottom: 0; }
.table-wrap { width: 100%; overflow: visible; border: 1px solid var(--line); border-radius: 10px; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; }
th, td { padding: 10px 12px; border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); vertical-align: top; overflow-wrap: anywhere; }
th:last-child, td:last-child { border-right: 0; }
tbody tr:last-child td { border-bottom: 0; }
th { background: var(--accent-soft); text-align: left; color: var(--accent); font-size: 16px; }
td { font-size: 16px; }
.empty-state { margin: 0; padding: 18px; color: var(--muted); background: #f7f8fa; }
.scope-note { margin-bottom: 28px; padding: 18px 22px; border-left: 5px solid var(--warm); background: #fbf7f1; font-weight: 650; }
@media (max-width: 900px) {
  body { padding: 0; }
  .deck { gap: 0; }
  .slide { width: 100%; min-height: 100vh; aspect-ratio: auto; padding: 48px 24px 32px; border-left: 0; border-right: 0; box-shadow: none; }
  .cover-layout, .split { grid-template-columns: 1fr; }
  .card-grid { grid-template-columns: 1fr 1fr; }
}
@page { size: 13.333in 7.5in; margin: 0; }
@media print {
  html, body { background: white; }
  body { padding: 0; }
  .deck { display: block; }
  .slide {
    width: 13.333in;
    height: 7.5in;
    min-height: 0;
    aspect-ratio: auto;
    border: 0;
    box-shadow: none;
    break-after: page;
    page-break-after: always;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  .slide:last-child { break-after: auto; page-break-after: auto; }
}
""".strip()

_TIMELINE_PROFILE_CSS = r"""
html.timeline-profile-a .timeline.horizon-axis {
  position: relative;
  height: 430px;
  margin: 0 18px;
  padding: 0;
  border: 0;
  display: block;
}
html.timeline-profile-a .timeline.horizon-axis::before {
  content: "";
  position: absolute;
  left: 14%;
  right: 14%;
  top: 50%;
  height: 2px;
  background: #7895bf;
}
html.timeline-profile-a .axis-event {
  position: absolute;
  left: var(--timeline-position);
  top: 0;
  width: 0;
  height: 430px;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  display: block;
}
html.timeline-profile-a .axis-event::before {
  left: -8px;
  top: calc(50% - 8px);
  width: 12px;
  height: 12px;
  border: 2px solid #2f64c6;
  border-radius: 50%;
  background: white;
}
html.timeline-profile-a .axis-event::after {
  content: "";
  position: absolute;
  left: 0;
  width: 1px;
  background: #b5c3d8;
}
html.timeline-profile-a .axis-event:nth-child(odd)::after { top: 142px; height: 73px; }
html.timeline-profile-a .axis-event:nth-child(even)::after { top: 215px; height: 55px; }
html.timeline-profile-a .axis-label {
  position: absolute;
  left: -150px;
  width: 300px;
  text-align: center;
}
html.timeline-profile-a .axis-event:nth-child(odd) .axis-label { top: 32px; }
html.timeline-profile-a .axis-event:nth-child(even) .axis-label { top: 270px; }
html.timeline-profile-a .axis-label time {
  display: block;
  margin-bottom: 12px;
  color: #2f64c6;
  font-weight: 700;
}
html.timeline-profile-a .axis-label p { margin: 0; line-height: 1.48; }

html.timeline-profile-b .timeline.docket-register {
  position: relative;
  height: 430px;
  margin: 0;
  padding: 0;
  border: 0;
  display: block;
}
html.timeline-profile-b .docket-row {
  position: absolute;
  left: 0;
  top: var(--timeline-position);
  width: 100%;
  height: 104px;
  transform: translateY(-50%);
  padding: 16px 0 20px;
  border: 0;
  border-bottom: 1px solid #d7dee8;
  border-radius: 0;
  background: white;
  display: grid;
  grid-template-columns: 230px 1fr;
  gap: 0;
  align-items: center;
}
html.timeline-profile-b .docket-row::before {
  left: 225px;
  top: 45px;
  width: 8px;
  height: 8px;
  border: 0;
  border-radius: 0;
  background: #2f64c6;
}
html.timeline-profile-b .docket-row time {
  padding-right: 30px;
  color: #2f64c6;
  text-align: right;
  font-weight: 700;
}
html.timeline-profile-b .docket-row p {
  min-height: 72px;
  margin: 0;
  padding: 20px 18px 20px 36px;
  border-left: 1px solid #b8c2d0;
  display: flex;
  align-items: center;
}
""".strip()


def _build_document(
    delivery_ir: Mapping[str, Any], timeline_profile: str | None = None
) -> tuple[bytes, int]:
    if timeline_profile is not None and timeline_profile not in _TIMELINE_PROFILES:
        raise HtmlRenderError("timeline_profile must be a or b")
    _reject_pii_canary(delivery_ir)
    profile = _mapping(delivery_ir.get("profile", {}), "profile")
    _sequence(delivery_ir.get("sources", []), "sources")
    slides = _sequence(delivery_ir.get("slides"), "slides")
    if not slides:
        raise HtmlRenderError("slides must not be empty")
    watermark = _watermark(delivery_ir.get("release_state"))
    try:
        table_headers = visible_table_headers(delivery_ir.get("source_schema"))
    except ValueError as exc:
        raise HtmlRenderError(str(exc)) from exc
    rendered_slides = "".join(
        _render_slide(
            slide,
            index,
            profile,
            watermark,
            table_headers,
            timeline_profile,
        )
        for index, slide in enumerate(slides)
    )
    title_value = (
        profile.get("title")
        or profile.get("document_title")
        or profile.get("matter_label")
        or profile.get("matter_name")
        or "诉讼案件可视化报告"
    )
    html_open = (
        f'<html class="timeline-profile-{timeline_profile}" lang="zh-CN">'
        if timeline_profile is not None
        else '<html lang="zh-CN">'
    )
    css = (
        _CSS + "\n" + _TIMELINE_PROFILE_CSS
        if timeline_profile is not None
        else _CSS
    )
    document = (
        '<!doctype html>\n' + html_open + '<head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="referrer" content="no-referrer">'
        '<meta http-equiv="Content-Security-Policy" content="default-src &apos;none&apos;; '
        'style-src &apos;unsafe-inline&apos;; img-src data:; font-src &apos;none&apos;; '
        'script-src &apos;none&apos;; connect-src &apos;none&apos;; media-src &apos;none&apos;; '
        'object-src &apos;none&apos;; frame-src &apos;none&apos;; base-uri &apos;none&apos;; '
        'form-action &apos;none&apos;">'
        f'<title>{_escaped(title_value, "profile.title")}</title>'
        f'<style>{css}</style></head><body><div class="deck">{rendered_slides}</div>'
        '</body></html>\n'
    )
    return document.encode("utf-8"), len(slides)


def render_html(
    delivery_ir: dict,
    output_path: Path,
    *,
    timeline_profile: str | None = None,
) -> dict:
    """Render and atomically commit one deterministic offline HTML file.

    Validation and document construction happen before the output parent is
    created, so malformed input produces no filesystem side effects.  The only
    temporary file is created beside the requested output, fsynced, and then
    replaced atomically.
    """

    if not isinstance(delivery_ir, dict):
        raise TypeError("delivery_ir must be a dict")
    if not isinstance(output_path, Path):
        raise TypeError("output_path must be pathlib.Path")
    if output_path.name in {"", ".", ".."}:
        raise HtmlRenderError("output_path must name a file")
    payload, slide_count = _build_document(
        _annotate_semantics(delivery_ir), timeline_profile
    )

    parent = output_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    if output_path.is_symlink():
        raise HtmlRenderError("output_path must not be a symlink")

    temp_path: Path | None = None
    try:
        fd, raw_temp_path = tempfile.mkstemp(
            prefix=f".{output_path.name}.", suffix=".tmp", dir=parent
        )
        temp_path = Path(raw_temp_path)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, output_path)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

    return {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
        "slide_count": slide_count,
        "timeline_profile": timeline_profile,
    }


__all__ = ["HtmlRenderError", "render_html"]
