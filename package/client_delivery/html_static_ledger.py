"""Closed expected ledger for fixed customer-visible HTML chrome.

This module is deliberately independent from the HTML writer and from both
actual-artifact enumerators.  The always-run HTML parser and the real-browser
gate share only this DeliveryIR-derived contract; neither trusts HTML-declared
hashes as the expected result.
"""

from __future__ import annotations

from typing import Any

from .delivery_ir import visible_table_headers


ROLE_LABEL_BY_ROLE = {
    "cover": "案件概览",
    "executive_summary": "执行摘要",
    "relationship": "主体关系",
    "timeline": "关键时间线",
    "evidence_matrix": "要件与证据",
    "stage_risk": "阶段与风险",
    "next_steps": "缺口与下一步",
    "scope": "范围与说明",
}
PROFILE_FIELDS = (
    ("client_label", "客户"),
    ("matter_label", "项目"),
    ("case_ref", "案件编号"),
    ("version", "版本"),
    ("materials_as_of", "材料截止日"),
    ("prepared_by", "编制"),
    ("confidentiality", "保密级别"),
)
PROFILE_ALIASES = {
    "client_label": ("client_name",),
    "matter_label": ("matter_name", "case_name"),
    "materials_as_of": ("as_of_date",),
}
DISPLAY_REVIEW_STATE = "审阅稿"
DISPLAY_DOCUMENT_LABEL = "诉讼可视化"
DISPLAY_CONFIDENTIALITY = {
    "CONFIDENTIAL": "机密",
    "ATTORNEY_WORK_PRODUCT": "律师工作成果",
    "INTERNAL_REVIEW_ONLY": "仅供内部审阅",
}


class StaticLedgerError(ValueError):
    """Raised when DeliveryIR cannot yield one exact static ledger."""


def build_expected_static_ledger(delivery_ir: dict[str, Any]) -> list[dict[str, Any]]:
    """Return per-page fixed chrome with mixed-owner ordinal and exact text."""

    slides = delivery_ir.get("slides")
    profile = delivery_ir.get("profile")
    inventory = delivery_ir.get("semantic_inventory")
    if not isinstance(slides, list) or not isinstance(profile, dict) or not isinstance(inventory, list):
        raise StaticLedgerError("DeliveryIR缺少闭合字段")
    semantic_locations = {
        (item.get("slide_id"), item.get("slot"), item.get("item_index"))
        for item in inventory
        if isinstance(item, dict)
    }
    try:
        table_headers = visible_table_headers(delivery_ir.get("source_schema"))
    except ValueError as exc:
        raise StaticLedgerError("DeliveryIR表头契约无效") from exc
    result: list[dict[str, Any]] = []

    def text_value(value: Any) -> str:
        if isinstance(value, dict):
            value = value.get("text")
        if not isinstance(value, str):
            raise StaticLedgerError("DeliveryIR文本无效")
        return value.strip()

    for position, slide in enumerate(slides):
        if not isinstance(slide, dict) or not isinstance(slide.get("content"), dict):
            raise StaticLedgerError("DeliveryIR slide无效")
        slide_id = slide.get("slide_id")
        role = slide.get("role")
        content = slide["content"]
        if not isinstance(slide_id, str) or role not in ROLE_LABEL_BY_ROLE:
            raise StaticLedgerError("DeliveryIR role无效")
        owners: list[dict[str, str] | None] = []

        def semantic(count: int = 1) -> None:
            owners.extend([None] * count)

        def static(static_id: str, value: str) -> None:
            owners.append({"id": static_id, "text": value})

        def semantic_items(slot: str) -> None:
            values = content.get(slot, [])
            if not isinstance(values, list):
                raise StaticLedgerError(f"DeliveryIR列表无效:{slide_id}:{slot}")
            semantic(len(values))

        def static_table(slot: str, label: str, header: list[str]) -> None:
            rows = content.get(slot, [])
            if not isinstance(rows, list):
                raise StaticLedgerError(f"DeliveryIR表格无效:{slide_id}:{slot}")
            if not rows:
                static(f"{label}:empty", "本节暂无已确认条目。")
                return
            first = rows[0]
            cells = first.get("cells") if isinstance(first, dict) else None
            if not isinstance(cells, list):
                raise StaticLedgerError(f"DeliveryIR表格行无效:{slide_id}:{slot}")
            if len(cells) == len(header) and [str(value) for value in cells] != header:
                static(f"{label}:header", "".join(header))
            semantic(len(rows))

        static("watermark:release-state", DISPLAY_REVIEW_STATE)
        if role == "cover":
            semantic(3)
            static(
                "cover-lead",
                "基于已冻结材料整理，用于律师与客户共同复核事实、证据和下一步安排。",
            )
            content_profile = content.get("profile", content)
            if not isinstance(content_profile, dict):
                raise StaticLedgerError("cover profile无效")
            merged = dict(profile)
            profile_keys = {key for key, _ in PROFILE_FIELDS}
            profile_keys.update(
                alias for aliases in PROFILE_ALIASES.values() for alias in aliases
            )
            profile_keys.update({"title", "document_title", "subtitle"})
            for key in profile_keys:
                if key in content_profile:
                    merged[key] = content_profile[key]

            def profile_value(key: str) -> Any:
                value = merged.get(key)
                if value is not None and value != "":
                    return value
                for alias in PROFILE_ALIASES.get(key, ()):
                    value = merged.get(alias)
                    if value is not None and value != "":
                        return value
                return None

            for key, label in PROFILE_FIELDS:
                if key in {"client_label", "matter_label"}:
                    continue
                value = profile_value(key)
                if value is None or value == "":
                    continue
                display = (
                    DISPLAY_CONFIDENTIALITY.get(value)
                    if key == "confidentiality"
                    else str(value)
                )
                if display is None:
                    raise StaticLedgerError(
                        "confidentiality缺少简体中文显示映射"
                    )
                static(f"cover-meta-label:{key}", label)
                if (slide_id, f"profile.{key}", 0) in semantic_locations:
                    semantic()
                else:
                    static(f"cover-meta-value:{key}", display)
        else:
            static("header:role-label", ROLE_LABEL_BY_ROLE[role])
            semantic()
            if role == "executive_summary":
                semantic_items("items")
            elif role == "relationship":
                if content.get("parties"):
                    static("relationship:parties-heading", "相关主体")
                    semantic_items("parties")
                if content.get("chain"):
                    static("relationship:chain-heading", "关系链条")
                    semantic_items("chain")
            elif role == "timeline":
                semantic_items("events")
                if content.get("undated_milestones"):
                    static("timeline:undated-heading", "未定日期里程碑")
                    semantic_items("undated_milestones")
            elif role == "evidence_matrix":
                if content.get("rows"):
                    static("evidence:matrix-heading", "要件—证据矩阵")
                    static_table("rows", "evidence_matrix.rows", table_headers["matrix"])
                if content.get("amounts"):
                    static("evidence:amounts-heading", "金额事项")
                    static_table(
                        "amounts", "evidence_matrix.amounts", table_headers["amounts"]
                    )
                if content.get("amount_notes"):
                    static("evidence:amount-notes-heading", "金额口径说明")
                    semantic_items("amount_notes")
                if content.get("evidence_index"):
                    static("evidence:index-heading", "证据索引")
                    semantic_items("evidence_index")
            elif role == "stage_risk":
                if content.get("stages"):
                    static("stage-risk:stages-heading", "程序阶段")
                    static_table("stages", "stage_risk.stages", table_headers["stages"])
                if content.get("risks"):
                    static("stage-risk:risks-heading", "风险事项")
                    static_table("risks", "stage_risk.risks", table_headers["risks"])
            elif role == "next_steps":
                if content.get("items"):
                    static("next-steps:items-heading", "下一步行动")
                    semantic_items("items")
                if content.get("gaps"):
                    static("next-steps:gaps-heading", "待补证据或信息")
                    semantic_items("gaps")
            elif role == "scope":
                boundary = content.get("boundary")
                boundary_text = (
                    "本报告仅反映当前材料范围和复核状态，不替代律师对事实、法律与策略的最终判断。"
                    if boundary is None
                    else text_value(boundary)
                )
                static("scope:boundary", boundary_text)
                if content.get("materials_as_of") is not None:
                    static(
                        "scope:cutoff",
                        "材料截止日：" + text_value(content["materials_as_of"]),
                    )
                semantic_items("items")
        static("footer:document-label", DISPLAY_DOCUMENT_LABEL)
        refs = slide.get("source_refs", [])
        if not isinstance(refs, list):
            raise StaticLedgerError("source_refs无效")
        if refs:
            static("footer:source-refs", "来源索引：" + " · ".join(map(str, refs)))
        static("footer:page-number", f"{position + 1:02d}")
        static_entries = [
            {"owner_ordinal": ordinal, **owner}
            for ordinal, owner in enumerate(owners)
            if owner is not None
        ]
        result.append(
            {
                "slide_index": position + 1,
                "slide_id": slide_id,
                "role": role,
                "owner_count": len(owners),
                "static": static_entries,
            }
        )
    return result
