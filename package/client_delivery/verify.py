"""Structural, privacy, offline and native-editability checks for S2 outputs."""

from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
import math
import os
import posixpath
import re
import stat
import tempfile
import uuid
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr

from .semantic_inventory import SemanticInventoryError, compare_rendered_inventory
from .delivery_ir import visible_table_headers


MAX_ZIP_MEMBERS = 4000
MAX_UNCOMPRESSED_BYTES = 80 * 1024 * 1024
FORBIDDEN_MEMBER_FRAGMENTS = (
    "vbaproject",
    "activex",
    "embeddings/",
    "comments",
    "customxml/",
    "oleobject",
)
FORBIDDEN_TEXT = (
    b"/Users/",
    b"/home/",
    b"\x5cUsers\x5c",
    b"file://",
    b"/private/tmp/",
    b"/var/folders/",
    b"PII_CANARY",
)
RANDOM_REL_ID_RE = re.compile(br"R[0-9A-Fa-f]{16}")
RANDOM_SHAPE_CREATION_RE = re.compile(
    br'(?<=creationId id=")\{[0-9A-Fa-f-]{36}\}'
)
RANDOM_SLIDE_CREATION_RE = re.compile(br'(?<=p14:creationId val=")\d+')
SEMANTIC_NAME_RE = re.compile(r"\|SEMITEM\|(sem:[A-Za-z0-9._:-]+)\|")
SEMANTIC_HTML_RE = re.compile(r'\bdata-semantic-id="(sem:[A-Za-z0-9._:-]+)"')
STATIC_HTML_ID_RE = re.compile(
    r"^(?:watermark:release-state|header:role-label|"
    r"footer:(?:document-label|source-refs|page-number)|cover-lead|"
    r"cover-meta-(?:label|value):(?:case_ref|version|materials_as_of|prepared_by|confidentiality)|"
    r"relationship:(?:parties|chain)-heading|timeline:undated-heading|"
    r"evidence:(?:matrix|amounts|amount-notes|index)-heading|stage-risk:(?:stages|risks)-heading|"
    r"next-steps:(?:items|gaps)-heading|scope:(?:boundary|cutoff)|"
    r"(?:evidence_matrix\.(?:rows|amounts)|stage_risk\.(?:stages|risks)):(?:header|empty))$"
)
DELIVERY_FONT = "Microsoft YaHei"
DISPLAY_SERIES = "诉讼可视化简报"
DISPLAY_EYEBROW = "诉讼可视化简报 · 客户审阅材料"
DISPLAY_REVIEW_STATE = "审阅稿"
DISPLAY_DOCUMENT_LABEL = "诉讼可视化"
HTML_STYLE_SHA256 = "52bfe118884db0931c96c445d9d667660058420beae798717fa9abfe0b0bb59d"
DISPLAY_CONFIDENTIALITY = {
    "CONFIDENTIAL": "机密",
    "ATTORNEY_WORK_PRODUCT": "律师工作成果",
    "INTERNAL_REVIEW_ONLY": "仅供内部审阅",
}
DISPLAY_PRESENTATION_FORMAT = "宽屏 (16:9)"
APP_LPSTR_DISPLAY = {
    "Theme": "主题",
    "Slide Titles": "幻灯片标题",
    "Office Theme": "诉讼可视化主题",
}
DISPLAY_THEME_NAME = APP_LPSTR_DISPLAY["Office Theme"]
DISPLAY_THEME_SCHEME_NAMES = {
    "clrScheme": "诉讼可视化配色",
    "fontScheme": "诉讼可视化字体",
    "fmtScheme": "诉讼可视化格式",
}
EDITABLE_TEMPLATE_TEXT_DISPLAY = {
    "Click to edit Master title style": "单击以编辑母版标题样式",
    "Click to edit Master text styles": "单击以编辑母版文本样式",
    "Click to edit Master subtitle style": "单击以编辑母版副标题样式",
    "Second level": "第二级",
    "Third level": "第三级",
    "Fourth level": "第四级",
    "Fifth level": "第五级",
    "1/27/13": "2013年1月27日",
    "10/17/16": "2016年10月17日",
    "‹#›": "‹页码›",
}
EDITABLE_LAYOUT_NAME_DISPLAY = {
    "Blank": "空白",
    "Comparison": "比较",
    "Content with Caption": "带说明的内容",
    "Picture with Caption": "带说明的图片",
    "Section Header": "节标题",
    "Title Only": "仅标题",
    "Title Slide": "标题幻灯片",
    "Title and Content": "标题和内容",
    "Title and Vertical Text": "标题和竖排文本",
    "Two Content": "两栏内容",
    "Vertical Title and Text": "竖排标题和文本",
}
EDITABLE_PLACEHOLDER_NAME_DISPLAY = {
    "Content Placeholder": "内容占位符",
    "Date Placeholder": "日期占位符",
    "Footer Placeholder": "页脚占位符",
    "Header Placeholder": "页眉占位符",
    "Notes Placeholder": "备注占位符",
    "Picture Placeholder": "图片占位符",
    "Slide Image Placeholder": "幻灯片图像占位符",
    "Slide Number Placeholder": "幻灯片编号占位符",
    "Subtitle": "副标题",
    "Text Placeholder": "文本占位符",
    "Title": "标题",
    "Title Placeholder": "标题占位符",
    "Vertical Text Placeholder": "竖排文本占位符",
    "Vertical Title": "竖排标题",
}
EDITABLE_TEMPLATE_PARTS = {
    "ppt/slideMasters/slideMaster1.xml",
    "ppt/notesMasters/notesMaster1.xml",
    *{f"ppt/slideLayouts/slideLayout{index}.xml" for index in range(1, 12)},
}
THEME_PARTS = {"ppt/theme/theme1.xml", "ppt/theme/theme2.xml"}
APP_PROPERTIES_SEMANTIC_SHA256_WITH_COUNT_TOKENS = (
    "f33dc79977d1ef816833021971e11e8badd839ececf2ab9ed5097020dc90d115"
)
EXACT_XML_SEMANTIC_SHA256 = {
    "docProps/core.xml": "5dbc95d3064a3c20ea9276f74d88307528a9fb33bf502cf525355c0071784831",
    "ppt/notesMasters/notesMaster1.xml": "d914a20de17da0a5678627a9cbc91bbfd12054c3ceb5a80b8038ebe313d82d43",
    "ppt/slideLayouts/slideLayout1.xml": "05c3cc693776eaf0a2451d113171e15576da4279ca7c8a9f339ff90af1177c8c",
    "ppt/slideLayouts/slideLayout10.xml": "670ff3449f38ad7318a600f8a4fe04f3eb84894e64d882dff288fec1871b8889",
    "ppt/slideLayouts/slideLayout11.xml": "f647d2f5c80f4bea517c69610eb330f7bfae2453605fc1a29e46e4709bd8aeb8",
    "ppt/slideLayouts/slideLayout2.xml": "7f802b32d250cd0bfa4151dcb77034de17ea4c91d89e65bb67d951b8c0fc4d29",
    "ppt/slideLayouts/slideLayout3.xml": "4e7e10a2c5516a6ad771798de7d93cfe016095ace61a70ce9e7e69fd1657c558",
    "ppt/slideLayouts/slideLayout4.xml": "22c329c86b4d3836f276dd97718f681f56a343e82691a95f8e4d843d70f58cac",
    "ppt/slideLayouts/slideLayout5.xml": "4282e15f7433db0db09d218b1733ef203b5f8072c8ffb07fa153830bb547a622",
    "ppt/slideLayouts/slideLayout6.xml": "e12b59175b19afc54ceb7e0f3d9127a2519b95b42254356434270b40376f97cb",
    "ppt/slideLayouts/slideLayout7.xml": "7b9b9dc53788cca3b19f93e595c82c1533cff4746a7152fc6efcbe245b335c07",
    "ppt/slideLayouts/slideLayout8.xml": "b429f504f9053e7ae8008b6b46f6cc37290e9fdb7a77e96269bf043c6760aa5a",
    "ppt/slideLayouts/slideLayout9.xml": "1e62260ca879fc095ee256d61b1d1dde9a710da1a219ea76fca50f20a60620cc",
    "ppt/slideMasters/slideMaster1.xml": "d95b1b974c5a2c531eac39d70ae5d45fefbf476748a02b313a790893745689c2",
    "ppt/theme/theme1.xml": "0692a3ff10a5d2d11deaa11cb115fa10d255d60b4fcb1d927d24962f83369f03",
    "ppt/theme/theme2.xml": "0692a3ff10a5d2d11deaa11cb115fa10d255d60b4fcb1d927d24962f83369f03",
}
DISPLAY_CORE_TITLE = "诉讼可视化简报（审阅稿）"
DISPLAY_CORE_SUBJECT = "原生可编辑客户审阅材料"
DISPLAY_CORE_DESCRIPTION = "审阅稿；须经人工法律复核与客户放行。"
DISPLAY_APPLICATION = "诉讼可视化交付工具"
NOTES_SOURCE_HEADING = "【来源】"
NOTES_BOUNDARY_HEADING = "【使用边界】"
NOTES_BOUNDARY_TEXT = "审阅稿；未自动取得客户放行。"
# Case- and separator-insensitive.  Covers the machine enums too: they are the
# authoritative internal values but must never surface as customer-visible
# chrome.  Kept byte-equivalent to the browser-side regex in html_qa.py so the
# always-run static parser is never the weaker of the two independent gates.
LEGACY_ENGLISH_CHROME_RE = re.compile(
    r"LITIGATION\s*BRIEF"
    r"|CLIENT[\s_-]*DELIVERY"
    r"|REVIEW[\s_-]*DRAFT"
    r"|CLIENT[\s_-]*READY"
    r"|INTERNAL[\s_-]*REVIEW[\s_-]*ONLY"
    r"|ATTORNEY[\s_-]*WORK[\s_-]*PRODUCT"
    r"|CONFIDENTIAL",
    re.IGNORECASE,
)


def _contains_legacy_english_chrome(value: str) -> bool:
    return bool(LEGACY_ENGLISH_CHROME_RE.search(value))


DISPLAY_ROLE_LABEL_BY_ROLE = {
    "cover": "案件概览",
    "executive_summary": "执行摘要",
    "relationship": "主体关系",
    "timeline": "关键时间线",
    "evidence_matrix": "要件与证据",
    "stage_risk": "阶段与风险",
    "next_steps": "缺口与下一步",
    "scope": "范围与说明",
}
DISPLAY_ROLE_LABELS = set(DISPLAY_ROLE_LABEL_BY_ROLE.values())
HTML_PROFILE_FIELDS = (
    ("client_label", "客户"),
    ("matter_label", "项目"),
    ("case_ref", "案件编号"),
    ("version", "版本"),
    ("materials_as_of", "材料截止日"),
    ("prepared_by", "编制"),
    ("confidentiality", "保密级别"),
)
HTML_PROFILE_ALIASES = {
    "client_label": ("client_name",),
    "matter_label": ("matter_name", "case_name"),
    "materials_as_of": ("as_of_date",),
}
TEXT_ROLE_NAME_RE = re.compile(r"\|TEXTROLE\|(DECK|SLIDE|MID|BODY|AUX)\|")
TEXT_ROLE_MINIMUM_HUNDREDTH_POINTS = {
    "DECK": 5000,
    "SLIDE": 3500,
    "MID": 2400,
    "BODY": 1600,
    "AUX": 800,
}
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
CORE_NS = {
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
}
APP_NS = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
VT_NS = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
A16_NS = "http://schemas.microsoft.com/office/drawing/2014/main"
P14_NS = "http://schemas.microsoft.com/office/powerpoint/2010/main"
DETERMINISTIC_UUID_NAMESPACE = uuid.UUID("e8438a8a-203b-5b5b-9b47-36a6d4516175")
RELATIONSHIP_ATTRS = {"Id", "Type", "Target", "TargetMode"}
EMU_PER_PIXEL = 9525
EMU_PER_POINT = 12700
CLOSED_PPTX_SLIDE_SIZE = {
    "cx": "12192000",
    "cy": "6858000",
    "type": "screen16x9",
}
DEFAULT_TEXT_STYLE_SEMANTIC_SHA256 = (
    "ba07daf19978f92c4d69d62715c037f0c6a7eafbff61cbb4eaad7c2f4d73a10a"
)
TIMELINE_SAFE_BOUNDS = tuple(
    value * EMU_PER_PIXEL for value in (64, 136, 1216, 638)
)
TIMELINE_MIN_ROW_GAP = 8 * EMU_PER_PIXEL
# LibreOffice 26.8 measured the longest canonical ISO date at 107.269996pt in
# the candidate's 16.5pt bold font.  Requiring 114pt of *inner* text width
# retains 6.73pt (6.3%) headroom for renderer/font-metric variation.  Scale
# the requirement if a future writer increases the date font size.
TIMELINE_DATE_REFERENCE_FONT_HUNDREDTH_POINTS = 1650
TIMELINE_DATE_LO_SAFE_INNER_WIDTH_EMU = 114 * EMU_PER_POINT
RELATIONSHIP_SAFE_BOUNDS = tuple(
    value * EMU_PER_PIXEL for value in (64, 136, 1216, 638)
)
RELATIONSHIP_MIN_ROW_GAP = 8 * EMU_PER_PIXEL


class VerificationError(ValueError):
    """Raised when a generated client artifact is not safe to commit."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _regular_file(path: Path) -> bool:
    try:
        return not path.is_symlink() and stat.S_ISREG(
            path.stat(follow_symlinks=False).st_mode
        )
    except OSError:
        return False


BBox = tuple[int, int, int, int]


def _shape_bboxes(root: ET.Element) -> dict[str, BBox]:
    """Extract final OOXML shape bounds keyed by stable native object name."""

    result: dict[str, BBox] = {}
    candidates = [
        (".//p:sp", "./p:nvSpPr/p:cNvPr"),
        (".//p:cxnSp", "./p:nvCxnSpPr/p:cNvPr"),
    ]
    for shape_path, properties_path in candidates:
        for shape in root.findall(shape_path, NS):
            properties = shape.find(properties_path, NS)
            transform = shape.find("./p:spPr/a:xfrm", NS)
            if properties is None or transform is None:
                continue
            name = properties.attrib.get("name", "")
            offset = transform.find("a:off", NS)
            extent = transform.find("a:ext", NS)
            if not name or offset is None or extent is None:
                continue
            try:
                left = int(offset.attrib["x"])
                top = int(offset.attrib["y"])
                width = int(extent.attrib["cx"])
                height = int(extent.attrib["cy"])
            except (KeyError, ValueError) as exc:
                raise VerificationError("PPTX shape bbox字段无效") from exc
            if width < 0 or height < 0:
                raise VerificationError("PPTX shape bbox为负")
            if name in result:
                raise VerificationError(f"PPTX原生对象名称重复:{name}")
            result[name] = (left, top, left + width, top + height)
    return result


def _shape_texts(root: ET.Element) -> dict[str, str]:
    """Extract exact visible text keyed by final native shape name."""

    result: dict[str, str] = {}
    for shape in root.findall(".//p:sp", NS):
        properties = shape.find("./p:nvSpPr/p:cNvPr", NS)
        if properties is None:
            continue
        name = properties.attrib.get("name", "")
        if not name:
            continue
        if name in result:
            raise VerificationError(f"PPTX原生对象名称重复:{name}")
        result[name] = "".join(node.text or "" for node in shape.findall(".//a:t", NS))
    return result


def _pptx_item_text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("text")
    if not isinstance(value, str):
        raise VerificationError("PPTX_VISIBLE_OBJECT_LEDGER_INVALID:DeliveryIR可见文本无效")
    return value.replace("\n", "")


def _pptx_table_text(header: list[str], rows: list[dict[str, Any]]) -> str:
    values: list[str] = [str(value or "") for value in header]
    for row in rows:
        cells = row.get("cells") if isinstance(row, dict) else None
        if not isinstance(cells, list):
            raise VerificationError(
                "PPTX_VISIBLE_OBJECT_LEDGER_INVALID:DeliveryIR表格行无效"
            )
        values.extend(str(value or "") for value in cells)
    return "".join(value.replace("\n", "") for value in values)


def _expected_pptx_objects(
    delivery_ir: dict[str, Any], slide: dict[str, Any], index: int
) -> dict[str, str]:
    """Rebuild the closed native object/text ledger from DeliveryIR.

    The ledger is deliberately independent from shape self-reporting.  Every
    writer-created ``p:sp``/``p:graphicFrame`` base name is known here and its
    exact OOXML-visible text is recomputed from the source IR or a closed
    chrome constant.  Consequently an added object, added text inside an
    existing semantic object, or a rewritten non-semantic label fails closed.
    """

    slide_id = slide.get("slide_id")
    role = slide.get("role")
    content = slide.get("content")
    if not isinstance(slide_id, str) or not isinstance(content, dict):
        raise VerificationError(
            "PPTX_VISIBLE_OBJECT_LEDGER_INVALID:DeliveryIR slide无效"
        )
    expected: dict[str, str] = {}
    table_headers = visible_table_headers(delivery_ir.get("source_schema"))

    def add(base: str, text: str = "") -> None:
        if base in expected:
            raise VerificationError(
                f"PPTX_VISIBLE_OBJECT_LEDGER_INVALID:预期对象重复:{slide_id}:{base}"
            )
        expected[base] = str(text).replace("\n", "")

    def bullets(prefix: str, values: Any) -> None:
        if not isinstance(values, list):
            raise VerificationError(
                "PPTX_VISIBLE_OBJECT_LEDGER_INVALID:DeliveryIR列表无效"
            )
        for item_index, item in enumerate(values):
            add(f"{prefix}:marker:{item_index}", str(item_index + 1))
            add(f"{prefix}:item:{item_index}", _pptx_item_text(item))

    if role == "cover":
        profile = delivery_ir.get("profile")
        if not isinstance(profile, dict):
            raise VerificationError(
                "PPTX_VISIBLE_OBJECT_LEDGER_INVALID:DeliveryIR profile无效"
            )
        add(f"{slide_id}:series", DISPLAY_SERIES)
        add(f"{slide_id}:matter", profile.get("matter_label", ""))
        add(f"{slide_id}:client", profile.get("client_label", ""))
        add(
            f"{slide_id}:meta",
            f"材料截止：{profile.get('materials_as_of', '')}"
            f"编制：{profile.get('prepared_by', '')}",
        )
        confidentiality = str(profile.get("confidentiality", ""))
        if confidentiality not in DISPLAY_CONFIDENTIALITY:
            raise VerificationError(
                "PPTX_VISIBLE_OBJECT_LEDGER_INVALID:confidentiality缺少简体中文显示映射"
            )
        add(
            f"{slide_id}:draft",
            DISPLAY_REVIEW_STATE + DISPLAY_CONFIDENTIALITY[confidentiality],
        )
        add(f"{slide_id}:boundary", "零格式返工目标 · 不替代律师终审与客户放行")
        return expected

    total = len(delivery_ir.get("slides", []))
    add(f"{slide_id}:eyebrow", DISPLAY_EYEBROW)
    add(f"{slide_id}:title", slide.get("title", ""))
    add(f"{slide_id}:release-state", DISPLAY_REVIEW_STATE)
    add(f"{slide_id}:header-rule")
    add(f"{slide_id}:page", f"{index + 1:02d} / {total:02d}")

    if role == "executive_summary":
        bullets(slide_id, content.get("items"))
    elif role == "relationship":
        parties = content.get("parties")
        chain = content.get("chain")
        if not isinstance(parties, list) or not isinstance(chain, list):
            raise VerificationError(
                "PPTX_VISIBLE_OBJECT_LEDGER_INVALID:relationship列表无效"
            )
        if parties:
            for item_index, item in enumerate(parties):
                add(f"{slide_id}:party:{item_index}", _pptx_item_text(item))
        else:
            for item_index, item in enumerate(chain):
                add(f"{slide_id}:chain-row:{item_index}")
                add(f"{slide_id}:chain-marker:{item_index}")
                add(f"{slide_id}:chain-text:{item_index}", _pptx_item_text(item))
    elif role == "timeline":
        events = content.get("events")
        milestones = content.get("undated_milestones")
        if not isinstance(events, list) or not isinstance(milestones, list):
            raise VerificationError(
                "PPTX_VISIBLE_OBJECT_LEDGER_INVALID:timeline列表无效"
            )
        if len(events) > 1:
            add(f"{slide_id}:timeline-guide")
        for item_index, event in enumerate(events):
            if not isinstance(event, dict):
                raise VerificationError(
                    "PPTX_VISIBLE_OBJECT_LEDGER_INVALID:timeline事件无效"
                )
            add(f"{slide_id}:event-date:{item_index}", event.get("date", ""))
            add(f"{slide_id}:event-marker:{item_index}")
            add(f"{slide_id}:event-text:{item_index}", event.get("text", ""))
        if milestones:
            add(f"{slide_id}:undated-panel")
            add(f"{slide_id}:undated-title", "未系日期事项")
            bullets(f"{slide_id}:undated", milestones)
    elif role == "evidence_matrix":
        rows = content.get("rows")
        amounts = content.get("amounts")
        amount_notes = content.get("amount_notes")
        evidence = content.get("evidence_index")
        if not all(
            isinstance(value, list)
            for value in (rows, amounts, amount_notes, evidence)
        ):
            raise VerificationError(
                "PPTX_VISIBLE_OBJECT_LEDGER_INVALID:evidence列表无效"
            )
        if rows:
            add(
                f"{slide_id}:matrix",
                _pptx_table_text(table_headers["matrix"], rows),
            )
        elif amounts:
            add(
                f"{slide_id}:amounts",
                _pptx_table_text(table_headers["amounts"], amounts),
            )
        elif amount_notes:
            bullets(f"{slide_id}:amount-notes", amount_notes)
        else:
            bullets(f"{slide_id}:evidence", evidence)
    elif role == "stage_risk":
        stages = content.get("stages")
        risks = content.get("risks")
        if not isinstance(stages, list) or not isinstance(risks, list):
            raise VerificationError(
                "PPTX_VISIBLE_OBJECT_LEDGER_INVALID:stage-risk列表无效"
            )
        if stages:
            add(
                f"{slide_id}:stages",
                _pptx_table_text(table_headers["stages"], stages),
            )
        else:
            add(
                f"{slide_id}:risks",
                _pptx_table_text(table_headers["risks"], risks),
            )
    elif role == "next_steps":
        items = content.get("items")
        gaps = content.get("gaps")
        if not isinstance(items, list) or not isinstance(gaps, list):
            raise VerificationError(
                "PPTX_VISIBLE_OBJECT_LEDGER_INVALID:next-steps列表无效"
            )
        if items:
            bullets(f"{slide_id}:actions", items)
        else:
            add(f"{slide_id}:gaps-panel")
            bullets(f"{slide_id}:gaps", gaps)
    elif role == "scope":
        bullets(f"{slide_id}:scope", content.get("items"))
        profile = delivery_ir.get("profile")
        if not isinstance(profile, dict):
            raise VerificationError(
                "PPTX_VISIBLE_OBJECT_LEDGER_INVALID:DeliveryIR profile无效"
            )
        add(
            f"{slide_id}:boundary-panel",
            "材料截止"
            + str(profile.get("materials_as_of", ""))
            + "状态"
            + DISPLAY_REVIEW_STATE
            + "边界"
            + "零格式返工不替代事实、法律、策略、隐私与律师终审。",
        )
        add(
            f"{slide_id}:no-release",
            "未经指定律师终审与客户放行，不得标记为客户可交付或外发。",
        )
    else:
        raise VerificationError(
            f"PPTX_VISIBLE_OBJECT_LEDGER_INVALID:未知role:{role}"
        )
    return expected


def _verify_pptx_visible_object_ledger(
    root: ET.Element,
    delivery_ir: dict[str, Any],
    slide: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    expected = _expected_pptx_objects(delivery_ir, slide, index)
    actual: dict[str, str] = {}
    no_wrap_bases = {
        f"{slide['slide_id']}:series",
        f"{slide['slide_id']}:draft",
        f"{slide['slide_id']}:eyebrow",
        f"{slide['slide_id']}:release-state",
    }
    verified_no_wrap = 0
    for container_path, properties_path in (
        (".//p:sp", "./p:nvSpPr/p:cNvPr"),
        (".//p:graphicFrame", "./p:nvGraphicFramePr/p:cNvPr"),
        (".//p:cxnSp", "./p:nvCxnSpPr/p:cNvPr"),
    ):
        for container in root.findall(container_path, NS):
            properties = container.find(properties_path, NS)
            name = properties.attrib.get("name", "") if properties is not None else ""
            if not name:
                raise VerificationError(
                    f"PPTX_VISIBLE_OBJECT_LEDGER_INVALID:第{index + 1}页对象无稳定名称"
                )
            base = name.split("|", 1)[0]
            if not base or base in actual:
                raise VerificationError(
                    f"PPTX_VISIBLE_OBJECT_LEDGER_INVALID:第{index + 1}页对象base重复:{base}"
                )
            actual[base] = "".join(
                node.text or "" for node in container.findall(".//a:t", NS)
            )
            if base in no_wrap_bases:
                body_properties = container.find("./p:txBody/a:bodyPr", NS)
                if body_properties is None or body_properties.attrib.get("wrap") != "none":
                    raise VerificationError(
                        "PPTX_FIXED_CHROME_INVALID:"
                        f"第{index + 1}页固定中文标签必须禁止自动换行:{base}"
                    )
                verified_no_wrap += 1
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    rewritten = sorted(
        base for base in set(expected).intersection(actual) if expected[base] != actual[base]
    )
    if missing or extra or rewritten:
        raise VerificationError(
            "PPTX_VISIBLE_OBJECT_LEDGER_INVALID:"
            f"第{index + 1}页原生对象/文本未闭合:"
            f"missing={missing[:3]}:extra={extra[:3]}:rewritten={rewritten[:3]}"
        )
    return {
        "status": "complete",
        "object_count": len(actual),
        "text_object_count": sum(bool(value.strip()) for value in actual.values()),
        "extra_object_count": 0,
        "rewritten_text_object_count": 0,
        "fixed_chrome_no_wrap_count": verified_no_wrap,
    }


def _verify_ooxml_text_roles(root: ET.Element, slide_number: int) -> dict[str, Any]:
    """Validate exported OOXML point sizes, never source-library pixel sizes.

    Every visible client text container is explicitly named with a semantic
    role and its final ``a:rPr/@sz`` value is the authority.  Unmarked visible
    text fails closed so future renderer additions cannot bypass the
    typography contract, regardless of which portable writer created OOXML.
    """

    candidates = [
        (".//p:sp", "./p:nvSpPr/p:cNvPr"),
        (".//p:graphicFrame", "./p:nvGraphicFramePr/p:cNvPr"),
    ]
    counts: Counter[str] = Counter()
    minimum_seen: dict[str, int] = {}
    visible_containers = 0
    visible_runs = 0
    for container_path, properties_path in candidates:
        for container in root.findall(container_path, NS):
            visible_text = "".join(
                node.text or "" for node in container.findall(".//a:t", NS)
            )
            if not visible_text.strip():
                continue
            properties = container.find(properties_path, NS)
            name = properties.attrib.get("name", "") if properties is not None else ""
            roles = TEXT_ROLE_NAME_RE.findall(name)
            if len(roles) != 1:
                raise VerificationError(
                    f"PPTX_TEXT_ROLE_INVALID:第{slide_number}页可见文字对象缺失唯一角色:{name or '<unnamed>'}"
                )
            role = roles[0]
            threshold = TEXT_ROLE_MINIMUM_HUNDREDTH_POINTS[role]
            sized_runs = 0
            for run_path in (".//a:r", ".//a:fld"):
                for run in container.findall(run_path, NS):
                    run_text = "".join(
                        node.text or "" for node in run.findall(".//a:t", NS)
                    )
                    if not run_text.strip():
                        continue
                    properties_node = run.find("a:rPr", NS)
                    raw_size = (
                        properties_node.attrib.get("sz")
                        if properties_node is not None
                        else None
                    )
                    try:
                        size = int(raw_size) if raw_size is not None else -1
                    except ValueError as exc:
                        raise VerificationError(
                            f"PPTX_TEXT_SIZE_INVALID:第{slide_number}页字号字段无效:{name}"
                        ) from exc
                    if size < threshold:
                        raise VerificationError(
                            f"PPTX_TEXT_SIZE_INVALID:第{slide_number}页{role}实际字号不足:"
                            f"{name}:actual={size / 100:.2f}pt:required={threshold / 100:.2f}pt"
                        )
                    if properties_node is None or properties_node.attrib.get("lang") != "zh-CN":
                        raise VerificationError(
                            f"PPTX_TEXT_LANGUAGE_INVALID:第{slide_number}页文字未标记简体中文:{name}"
                        )
                    for font_tag in ("a:latin", "a:ea", "a:cs"):
                        font_node = properties_node.find(font_tag, NS)
                        if font_node is None or font_node.attrib.get("typeface") != DELIVERY_FONT:
                            raise VerificationError(
                                "PPTX_TEXT_FONT_INVALID:"
                                f"第{slide_number}页文字未使用大陆交付字体{DELIVERY_FONT}:{name}"
                            )
                    sized_runs += 1
                    visible_runs += 1
                    minimum_seen[role] = min(minimum_seen.get(role, size), size)
            if sized_runs < 1:
                raise VerificationError(
                    f"PPTX_TEXT_SIZE_INVALID:第{slide_number}页可见文字缺少显式run字号:{name}"
                )
            counts[role] += 1
            visible_containers += 1
    if visible_containers < 1 or visible_runs < 1:
        raise VerificationError(f"PPTX_TEXT_SIZE_INVALID:第{slide_number}页无可验证文字")
    return {
        "status": "pass",
        "authority": "final_ooxml_a:rPr_sz",
        "visible_containers": visible_containers,
        "visible_runs": visible_runs,
        "role_counts": dict(sorted(counts.items())),
        "minimum_actual_points": {
            role: value / 100 for role, value in sorted(minimum_seen.items())
        },
    }


def _verify_openxml_child_order(root: ET.Element, slide_number: int) -> dict[str, Any]:
    """Enforce the schema-significant child order emitted by the writer.

    Open XML validators treat these sequences as ordered content models.  A
    presentation can remain readable while still being schema-invalid, so the
    package verifier independently checks the two writer-customized element
    families rather than relying on application repair behavior.
    """

    character_rank = {
        "ln": 0,
        "noFill": 1,
        "solidFill": 1,
        "gradFill": 1,
        "blipFill": 1,
        "pattFill": 1,
        "grpFill": 1,
        "effectLst": 2,
        "effectDag": 2,
        "highlight": 3,
        "uLnTx": 4,
        "uLn": 4,
        "uFillTx": 5,
        "uFill": 5,
        "latin": 6,
        "ea": 7,
        "cs": 8,
        "sym": 9,
        "hlinkClick": 10,
        "hlinkMouseOver": 11,
        "rtl": 12,
        "extLst": 13,
    }
    cell_rank = {
        "lnL": 0,
        "lnR": 1,
        "lnT": 2,
        "lnB": 3,
        "lnTlToBr": 4,
        "lnBlToTr": 5,
        "cell3D": 6,
        "noFill": 7,
        "solidFill": 7,
        "gradFill": 7,
        "blipFill": 7,
        "pattFill": 7,
        "grpFill": 7,
        "headers": 8,
        "extLst": 9,
    }

    def require_order(elements: list[ET.Element], ranks: dict[str, int], label: str) -> int:
        checked = 0
        for element in elements:
            names = [child.tag.rsplit("}", 1)[-1] for child in element]
            known = [(name, ranks[name]) for name in names if name in ranks]
            if [rank for _, rank in known] != sorted(rank for _, rank in known):
                raise VerificationError(
                    "PPTX_OPENXML_CHILD_ORDER_INVALID:"
                    f"第{slide_number}页{label}子元素顺序无效:{names}"
                )
            checked += 1
        return checked

    run_properties = root.findall(".//a:rPr", NS)
    cell_properties = root.findall(".//a:tcPr", NS)
    return {
        "status": "pass",
        "run_properties_checked": require_order(
            run_properties, character_rank, "a:rPr"
        ),
        "table_cell_properties_checked": require_order(
            cell_properties, cell_rank, "a:tcPr"
        ),
    }


def _matching_names(values: dict[str, Any], prefix: str) -> list[str]:
    return sorted(
        name for name in values if name == prefix or name.startswith(prefix + "|")
    )


def _one_bbox(
    boxes: dict[str, BBox], prefix: str, *, gate: str = "TIMELINE_LAYOUT_INVALID"
) -> BBox:
    names = _matching_names(boxes, prefix)
    if len(names) != 1:
        raise VerificationError(
            f"{gate}:对象数量异常:{prefix}:{len(names)}"
        )
    return boxes[names[0]]


def _one_shape(
    root: ET.Element, prefix: str, *, gate: str
) -> ET.Element:
    matches: list[ET.Element] = []
    for shape in root.findall(".//p:sp", NS):
        properties = shape.find("./p:nvSpPr/p:cNvPr", NS)
        name = properties.attrib.get("name", "") if properties is not None else ""
        if name == prefix or name.startswith(prefix + "|"):
            matches.append(shape)
    if len(matches) != 1:
        raise VerificationError(f"{gate}:对象数量异常:{prefix}:{len(matches)}")
    return matches[0]


def _one_text(
    texts: dict[str, str], prefix: str, *, gate: str
) -> str:
    names = _matching_names(texts, prefix)
    if len(names) != 1:
        raise VerificationError(f"{gate}:文本对象数量异常:{prefix}:{len(names)}")
    return texts[names[0]]


def _overlaps(first: BBox, second: BBox) -> bool:
    return (
        max(first[0], second[0]) < min(first[2], second[2])
        and max(first[1], second[1]) < min(first[3], second[3])
    )


def _crosses_text(guide_or_marker: BBox, text: BBox) -> bool:
    """Treat zero-width/height guide lines as geometry, not empty rectangles."""

    if guide_or_marker[0] == guide_or_marker[2]:
        x_intersects = text[0] < guide_or_marker[0] < text[2]
    else:
        x_intersects = max(guide_or_marker[0], text[0]) < min(
            guide_or_marker[2], text[2]
        )
    if guide_or_marker[1] == guide_or_marker[3]:
        y_intersects = text[1] < guide_or_marker[1] < text[3]
    else:
        y_intersects = max(guide_or_marker[1], text[1]) < min(
            guide_or_marker[3], text[3]
        )
    return x_intersects and y_intersects


def _union(first: BBox, second: BBox) -> BBox:
    return (
        min(first[0], second[0]),
        min(first[1], second[1]),
        max(first[2], second[2]),
        max(first[3], second[3]),
    )


def _verify_relationship_layout(
    root: ET.Element, slide_id: str, content: dict[str, Any]
) -> dict[str, Any]:
    """Enforce party/chain isolation and final native chain-row geometry."""

    boxes = _shape_bboxes(root)
    texts = _shape_texts(root)
    parties = content["parties"]
    chain = content["chain"]
    if bool(parties) == bool(chain):
        raise VerificationError(
            f"RELATIONSHIP_LAYOUT_INVALID:parties与chain必须XOR:{slide_id}"
        )
    if len(parties) > 6 or len(chain) > 3:
        raise VerificationError(
            f"RELATIONSHIP_LAYOUT_INVALID:单页容量超限:{slide_id}"
        )

    party_names = [name for name in boxes if name.startswith(f"{slide_id}:party:")]
    chain_names = [name for name in boxes if name.startswith(f"{slide_id}:chain-")]
    left_bound, top_bound, right_bound, bottom_bound = RELATIONSHIP_SAFE_BOUNDS

    if parties:
        if chain_names:
            raise VerificationError(
                f"RELATIONSHIP_LAYOUT_INVALID:party页含chain对象:{slide_id}"
            )
        if len(party_names) != len(parties):
            raise VerificationError(
                f"RELATIONSHIP_LAYOUT_INVALID:party对象数量异常:{slide_id}:{len(party_names)}"
            )
        domain_boxes: list[BBox] = []
        for index, item in enumerate(parties):
            prefix = f"{slide_id}:party:{index}"
            box = _one_bbox(boxes, prefix, gate="RELATIONSHIP_LAYOUT_INVALID")
            if _one_text(texts, prefix, gate="RELATIONSHIP_LAYOUT_INVALID") != item["text"]:
                raise VerificationError(
                    f"RELATIONSHIP_LAYOUT_INVALID:party文本不精确:{slide_id}:{index}"
                )
            domain_boxes.append(box)
        mode = "parties"
        chain_rows: list[BBox] = []
    else:
        if party_names:
            raise VerificationError(
                f"RELATIONSHIP_LAYOUT_INVALID:chain页含party对象:{slide_id}"
            )
        expected_chain_shapes = len(chain) * 3
        if len(chain_names) != expected_chain_shapes:
            raise VerificationError(
                f"RELATIONSHIP_LAYOUT_INVALID:chain对象数量异常:{slide_id}:{len(chain_names)}"
            )
        domain_boxes = []
        chain_rows = []
        for index, item in enumerate(chain):
            row_prefix = f"{slide_id}:chain-row:{index}"
            marker_prefix = f"{slide_id}:chain-marker:{index}"
            text_prefix = f"{slide_id}:chain-text:{index}"
            row_box = _one_bbox(
                boxes, row_prefix, gate="RELATIONSHIP_LAYOUT_INVALID"
            )
            marker_box = _one_bbox(
                boxes, marker_prefix, gate="RELATIONSHIP_LAYOUT_INVALID"
            )
            text_box = _one_bbox(
                boxes, text_prefix, gate="RELATIONSHIP_LAYOUT_INVALID"
            )
            if _one_text(texts, marker_prefix, gate="RELATIONSHIP_LAYOUT_INVALID"):
                raise VerificationError(
                    f"RELATIONSHIP_LAYOUT_INVALID:chain marker不得编号:{slide_id}:{index}"
                )
            if _one_text(texts, text_prefix, gate="RELATIONSHIP_LAYOUT_INVALID") != item["text"]:
                raise VerificationError(
                    f"RELATIONSHIP_LAYOUT_INVALID:chain正文不精确:{slide_id}:{index}"
                )
            vertical_overlap = max(marker_box[1], text_box[1]) < min(
                marker_box[3], text_box[3]
            )
            if (
                _overlaps(marker_box, text_box)
                or marker_box[2] >= text_box[0]
                or not vertical_overlap
            ):
                raise VerificationError(
                    f"RELATIONSHIP_LAYOUT_INVALID:marker与正文未形成独立同行列:{slide_id}:{index}"
                )
            for child in (marker_box, text_box):
                if (
                    child[0] < row_box[0]
                    or child[1] < row_box[1]
                    or child[2] > row_box[2]
                    or child[3] > row_box[3]
                ):
                    raise VerificationError(
                        f"RELATIONSHIP_LAYOUT_INVALID:chain内容越出行框:{slide_id}:{index}"
                    )
            chain_rows.append(row_box)
            domain_boxes.extend((row_box, marker_box, text_box))
        for index in range(1, len(chain_rows)):
            previous = chain_rows[index - 1]
            current = chain_rows[index]
            if _overlaps(previous, current):
                raise VerificationError(
                    f"RELATIONSHIP_LAYOUT_INVALID:相邻chain行重叠:{slide_id}:{index - 1}-{index}"
                )
            if current[1] <= previous[1]:
                raise VerificationError(
                    f"RELATIONSHIP_LAYOUT_INVALID:chain源顺序不可见:{slide_id}:{index}"
                )
            if current[1] - previous[3] < RELATIONSHIP_MIN_ROW_GAP:
                raise VerificationError(
                    f"RELATIONSHIP_LAYOUT_INVALID:相邻chain行间距小于8px:{slide_id}:{index - 1}-{index}"
                )
        mode = "chain"

    for box in domain_boxes:
        if (
            box[0] < left_bound
            or box[1] < top_bound
            or box[2] > right_bound
            or box[3] > bottom_bound
        ):
            raise VerificationError(
                f"RELATIONSHIP_LAYOUT_INVALID:对象越出安全区:{slide_id}"
            )
    return {
        "status": "pass",
        "mode": mode,
        "party_count": len(parties),
        "chain_count": len(chain),
        "party_chain_xor": True,
        "marker_text_separate_columns": True if chain else None,
        "visible_chain_numbering": False,
        "minimum_chain_row_gap_px": 8 if chain else None,
        "safe_bounds_px": [64, 136, 1216, 638],
    }


def _verify_timeline_layout(
    root: ET.Element, slide_id: str, content: dict[str, Any]
) -> dict[str, Any]:
    """Fail closed on the final native OOXML geometry, independent of screenshots."""

    boxes = _shape_bboxes(root)
    events = content["events"]
    milestones = content["undated_milestones"]
    event_boxes: list[BBox] = []
    text_boxes: list[BBox] = []
    marker_boxes: list[BBox] = []
    date_inner_widths: list[int] = []
    date_required_widths: list[int] = []
    for index in range(len(events)):
        date_box = _one_bbox(boxes, f"{slide_id}:event-date:{index}")
        date_shape = _one_shape(
            root,
            f"{slide_id}:event-date:{index}",
            gate="TIMELINE_LAYOUT_INVALID",
        )
        text_box = _one_bbox(boxes, f"{slide_id}:event-text:{index}")
        marker_box = _one_bbox(boxes, f"{slide_id}:event-marker:{index}")
        date_text = events[index].get("date")
        if not isinstance(date_text, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text) is None:
            raise VerificationError(
                f"TIMELINE_LAYOUT_INVALID:日期不是固定10字符ISO格式:{slide_id}:{index}"
            )
        body_properties = date_shape.find("./p:txBody/a:bodyPr", NS)
        if body_properties is None or body_properties.attrib.get("wrap") != "none":
            raise VerificationError(
                f"TIMELINE_LAYOUT_INVALID:日期单行禁止换行门缺失:{slide_id}:{index}"
            )
        try:
            left_inset = int(body_properties.attrib["lIns"])
            right_inset = int(body_properties.attrib["rIns"])
        except (KeyError, ValueError) as exc:
            raise VerificationError(
                f"TIMELINE_LAYOUT_INVALID:日期内边距无效:{slide_id}:{index}"
            ) from exc
        visible_runs = [
            run
            for run in date_shape.findall(".//a:r", NS)
            if "".join(node.text or "" for node in run.findall(".//a:t", NS)).strip()
        ]
        if len(visible_runs) != 1:
            raise VerificationError(
                f"TIMELINE_LAYOUT_INVALID:日期必须是单一可见run:{slide_id}:{index}"
            )
        run_properties = visible_runs[0].find("a:rPr", NS)
        try:
            font_size = int(run_properties.attrib["sz"]) if run_properties is not None else -1
        except ValueError as exc:
            raise VerificationError(
                f"TIMELINE_LAYOUT_INVALID:日期字号无效:{slide_id}:{index}"
            ) from exc
        if font_size <= 0:
            raise VerificationError(
                f"TIMELINE_LAYOUT_INVALID:日期字号缺失:{slide_id}:{index}"
            )
        inner_width = date_box[2] - date_box[0] - left_inset - right_inset
        required_width = math.ceil(
            TIMELINE_DATE_LO_SAFE_INNER_WIDTH_EMU
            * font_size
            / TIMELINE_DATE_REFERENCE_FONT_HUNDREDTH_POINTS
        )
        if inner_width < required_width:
            raise VerificationError(
                "TIMELINE_LAYOUT_INVALID:日期列LO-safe净宽不足:"
                f"{slide_id}:{index}:actual={inner_width / EMU_PER_POINT:.2f}pt:"
                f"required={required_width / EMU_PER_POINT:.2f}pt"
            )
        date_inner_widths.append(inner_width)
        date_required_widths.append(required_width)
        if _overlaps(date_box, text_box):
            raise VerificationError(
                f"TIMELINE_LAYOUT_INVALID:日期与正文重叠:{slide_id}:{index}"
            )
        vertical_overlap = max(date_box[1], text_box[1]) < min(
            date_box[3], text_box[3]
        )
        if not vertical_overlap or date_box[2] >= text_box[0]:
            raise VerificationError(
                f"TIMELINE_LAYOUT_INVALID:日期与正文未形成独立同行列:{slide_id}:{index}"
            )
        for label, text_region in (("date", date_box), ("text", text_box)):
            if _crosses_text(marker_box, text_region):
                raise VerificationError(
                    f"TIMELINE_LAYOUT_INVALID:marker穿越{label}:{slide_id}:{index}"
                )
        event_boxes.append(_union(date_box, text_box))
        text_boxes.extend((date_box, text_box))
        marker_boxes.append(marker_box)

    for index in range(1, len(event_boxes)):
        if _overlaps(event_boxes[index - 1], event_boxes[index]):
            raise VerificationError(
                f"TIMELINE_LAYOUT_INVALID:相邻事件框重叠:{slide_id}:{index - 1}-{index}"
            )
        if event_boxes[index][1] <= event_boxes[index - 1][1]:
            raise VerificationError(
                f"TIMELINE_LAYOUT_INVALID:事件顺序不可见:{slide_id}:{index}"
            )
        if event_boxes[index][1] - event_boxes[index - 1][3] < TIMELINE_MIN_ROW_GAP:
            raise VerificationError(
                f"TIMELINE_LAYOUT_INVALID:相邻事件行间距小于8px:{slide_id}:{index - 1}-{index}"
            )

    guide_names = [
        name for name in boxes if name == f"{slide_id}:timeline-guide"
    ]
    expected_guides = 1 if len(events) > 1 else 0
    if len(guide_names) != expected_guides:
        raise VerificationError(
            f"TIMELINE_LAYOUT_INVALID:纵向guide数量异常:{slide_id}:{len(guide_names)}"
        )
    guides = [boxes[name] for name in guide_names]
    for guide in guides:
        for text_region in text_boxes:
            if _crosses_text(guide, text_region):
                raise VerificationError(
                    f"TIMELINE_LAYOUT_INVALID:guide穿越文字:{slide_id}"
                )

    milestone_boxes = [
        _one_bbox(boxes, f"{slide_id}:undated:item:{index}")
        for index in range(len(milestones))
    ]
    protected = text_boxes + milestone_boxes
    for shape in guides + marker_boxes:
        for text_region in protected:
            if _crosses_text(shape, text_region):
                raise VerificationError(
                    f"TIMELINE_LAYOUT_INVALID:guide或marker穿越文字:{slide_id}"
                )
    if event_boxes and any(
        milestone[1] < max(event[3] for event in event_boxes)
        for milestone in milestone_boxes
    ):
        raise VerificationError(
            f"TIMELINE_LAYOUT_INVALID:未定日期事项侵入事件区:{slide_id}"
        )
    left_bound, top_bound, right_bound, bottom_bound = TIMELINE_SAFE_BOUNDS
    for box in text_boxes + marker_boxes + guides + milestone_boxes:
        if (
            box[0] < left_bound
            or box[1] < top_bound
            or box[2] > right_bound
            or box[3] > bottom_bound
        ):
            raise VerificationError(
                f"TIMELINE_LAYOUT_INVALID:对象越出安全区:{slide_id}"
            )
    return {
        "status": "pass",
        "event_count": len(events),
        "undated_count": len(milestones),
        "date_text_separate_columns": True,
        "adjacent_event_overlap": False,
        "minimum_row_gap_px": 8,
        "guide_or_marker_crosses_text": False,
        "date_single_line_guard": "wrap-none-and-width-pass",
        "minimum_date_inner_width_points": round(
            min(date_inner_widths) / EMU_PER_POINT, 2
        ) if date_inner_widths else None,
        "minimum_date_required_inner_width_points": round(
            min(date_required_widths) / EMU_PER_POINT, 2
        ) if date_required_widths else None,
        "date_lo_safe_reference": "LibreOffice-26.8-bold-107.269996pt-at-16.5pt-plus-6.73pt-headroom",
        "safe_bounds_px": [64, 136, 1216, 638],
    }


def _safe_zip_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    if not infos or len(infos) > MAX_ZIP_MEMBERS:
        raise VerificationError("PPTX ZIP成员数异常")
    names: set[str] = set()
    total = 0
    for info in infos:
        name = info.filename
        pure = PurePosixPath(name)
        if (
            not name
            or name in names
            or name.startswith("/")
            or ".." in pure.parts
            or "\\" in name
            or info.flag_bits & 0x1
        ):
            raise VerificationError("PPTX ZIP成员路径或加密状态异常")
        names.add(name)
        total += info.file_size
    if total > MAX_UNCOMPRESSED_BYTES:
        raise VerificationError("PPTX解压体积超限")
    return infos


def _xml_semantic_sha256(root: ET.Element) -> str:
    """Hash expanded tags, ordered children, exact text, and sorted attributes.

    Namespace prefixes and insignificant inter-element formatting are excluded;
    every semantic XML node, attribute, child position, and text value remains
    inside the closure.
    """

    def canonical(node: ET.Element) -> list[Any]:
        return [
            node.tag,
            sorted(node.attrib.items()),
            node.text or "",
            [canonical(child) for child in list(node)],
        ]

    payload = json.dumps(
        canonical(root), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _verify_pptx_document_properties(
    archive, *, slide_count: int, notes_count: int
) -> dict[str, Any]:
    """Fail closed when customer-visible document properties drift from the
    closed Simplified-Chinese display map.  Normalization rewrites a subset of
    these fields, so without this gate a writer regression is silently masked
    instead of rejected."""
    try:
        app_root = ET.fromstring(archive.read("docProps/app.xml"))
        core_root = ET.fromstring(archive.read("docProps/core.xml"))
    except (KeyError, ET.ParseError) as exc:
        raise VerificationError(
            "PPTX_DOC_PROPERTIES_INVALID:文档属性部件缺失或无法解析"
        ) from exc
    expected_core = {
        "dc:title": DISPLAY_CORE_TITLE,
        "dc:subject": DISPLAY_CORE_SUBJECT,
        "dc:creator": DISPLAY_APPLICATION,
        "dc:description": DISPLAY_CORE_DESCRIPTION,
        "cp:lastModifiedBy": DISPLAY_APPLICATION,
    }
    for path, expected in expected_core.items():
        node = core_root.find(path, CORE_NS)
        if node is None or (node.text or "") != expected:
            raise VerificationError(
                f"PPTX_DOC_PROPERTIES_INVALID:核心文档属性未使用简体中文显示值:{path}"
            )
    application = app_root.find(f"{{{APP_NS}}}Application")
    if application is None or (application.text or "") != DISPLAY_APPLICATION:
        raise VerificationError(
            "PPTX_DOC_PROPERTIES_INVALID:应用程序属性未使用简体中文显示值"
        )
    presentation_format = app_root.find(f"{{{APP_NS}}}PresentationFormat")
    if presentation_format is None or (
        presentation_format.text or ""
    ) != DISPLAY_PRESENTATION_FORMAT:
        raise VerificationError(
            "PPTX_DOC_PROPERTIES_INVALID:演示格式未使用简体中文显示值"
        )
    heading_pairs = app_root.find(f"{{{APP_NS}}}HeadingPairs")
    heading_vector = (
        heading_pairs.find(f"{{{VT_NS}}}vector")
        if heading_pairs is not None
        else None
    )
    expected_pairs = (("lpstr", "主题"), ("i4", "1"), ("lpstr", "幻灯片标题"), ("i4", "0"))
    actual_pairs: list[tuple[str, str]] = []
    if heading_vector is not None:
        for variant in list(heading_vector):
            children = list(variant)
            if variant.tag != f"{{{VT_NS}}}variant" or len(children) != 1:
                actual_pairs.append(("invalid", ""))
                continue
            child = children[0]
            actual_pairs.append((child.tag.rsplit("}", 1)[-1], child.text or ""))
    if (
        heading_vector is None
        or heading_vector.attrib != {"size": "4", "baseType": "variant"}
        or tuple(actual_pairs) != expected_pairs
    ):
        raise VerificationError(
            "PPTX_DOC_PROPERTIES_INVALID:HeadingPairs未与简体中文闭集精确一致"
        )
    titles = app_root.find(f"{{{APP_NS}}}TitlesOfParts")
    title_vector = titles.find(f"{{{VT_NS}}}vector") if titles is not None else None
    title_values = (
        [node.text or "" for node in list(title_vector)]
        if title_vector is not None
        else []
    )
    if (
        title_vector is None
        or title_vector.attrib != {"size": "1", "baseType": "lpstr"}
        or any(node.tag != f"{{{VT_NS}}}lpstr" for node in list(title_vector))
        or title_values != [DISPLAY_THEME_NAME]
    ):
        raise VerificationError(
            "PPTX_DOC_PROPERTIES_INVALID:TitlesOfParts未与简体中文闭集精确一致"
        )
    for node in app_root.iter():
        if _contains_legacy_english_chrome(node.text or ""):
            raise VerificationError(
                "PPTX_DOC_PROPERTIES_INVALID:扩展文档属性残留英文固定标签"
            )
    for node in core_root.iter():
        if _contains_legacy_english_chrome(node.text or ""):
            raise VerificationError(
                "PPTX_DOC_PROPERTIES_INVALID:核心文档属性残留英文固定标签"
            )
    slides_node = app_root.find(f"{{{APP_NS}}}Slides")
    notes_node = app_root.find(f"{{{APP_NS}}}Notes")
    if (
        slides_node is None
        or (slides_node.text or "") != str(slide_count)
        or notes_node is None
        or (notes_node.text or "") != str(notes_count)
    ):
        raise VerificationError("PPTX_DOC_PROPERTIES_INVALID:页数属性不精确")
    slides_node.text = "{SLIDE_COUNT}"
    notes_node.text = "{NOTES_COUNT}"
    app_digest = _xml_semantic_sha256(app_root)
    core_digest = _xml_semantic_sha256(core_root)
    if app_digest != APP_PROPERTIES_SEMANTIC_SHA256_WITH_COUNT_TOKENS:
        raise VerificationError("PPTX_DOC_PROPERTIES_INVALID:app.xml结构闭集不精确")
    if core_digest != EXACT_XML_SEMANTIC_SHA256["docProps/core.xml"]:
        raise VerificationError("PPTX_DOC_PROPERTIES_INVALID:core.xml结构闭集不精确")
    return {
        "status": "complete",
        "app_semantic_sha256_with_count_tokens": "sha256:" + app_digest,
        "core_semantic_sha256": "sha256:" + core_digest,
    }


def _editable_placeholder_name(value: str) -> str | None:
    """Return the closed Chinese placeholder name, preserving its template index."""

    for source, display in sorted(
        EDITABLE_PLACEHOLDER_NAME_DISPLAY.items(), key=lambda item: -len(item[0])
    ):
        match = re.fullmatch(rf"{re.escape(source)} (\d+)", value)
        if match:
            return f"{display} {match.group(1)}"
    for display in sorted(
        EDITABLE_PLACEHOLDER_NAME_DISPLAY.values(), key=len, reverse=True
    ):
        if re.fullmatch(rf"{re.escape(display)} \d+", value):
            return value
    return None


def _normalize_template_run_properties(properties: ET.Element) -> None:
    properties.attrib["lang"] = "zh-CN"
    font_tags = {f"{{{NS['a']}}}{local}" for local in ("latin", "ea", "cs")}
    children = list(properties)
    insertion = len(children)
    for index, child in enumerate(children):
        if child.tag.rsplit("}", 1)[-1] in {
            "sym",
            "hlinkClick",
            "hlinkMouseOver",
            "rtl",
            "extLst",
        }:
            insertion = min(insertion, index)
    for child in children:
        if child.tag in font_tags:
            child_index = list(properties).index(child)
            if child_index < insertion:
                insertion -= 1
            properties.remove(child)
    for offset, local in enumerate(("latin", "ea", "cs")):
        node = ET.Element(f"{{{NS['a']}}}{local}", {"typeface": DELIVERY_FONT})
        properties.insert(insertion + offset, node)


def _normalized_editable_template(name: str, raw: bytes) -> bytes:
    root = ET.fromstring(raw)
    for common_slide in root.iter(f"{{{NS['p']}}}cSld"):
        value = common_slide.attrib.get("name")
        if value is None:
            continue
        if value in EDITABLE_LAYOUT_NAME_DISPLAY:
            common_slide.attrib["name"] = EDITABLE_LAYOUT_NAME_DISPLAY[value]
        elif value not in EDITABLE_LAYOUT_NAME_DISPLAY.values():
            raise VerificationError(
                f"PPTX_EDITABLE_TEMPLATE_INVALID:未登记布局名称:{name}:{value}"
            )
    for properties in root.iter(f"{{{NS['p']}}}cNvPr"):
        value = properties.attrib.get("name", "")
        if not value:
            continue
        display = _editable_placeholder_name(value)
        if display is None:
            raise VerificationError(
                f"PPTX_EDITABLE_TEMPLATE_INVALID:未登记占位符名称:{name}:{value}"
            )
        properties.attrib["name"] = display
    allowed_template_text = set(EDITABLE_TEMPLATE_TEXT_DISPLAY.values())
    for node in root.iter(f"{{{NS['a']}}}t"):
        value = node.text or ""
        if value in EDITABLE_TEMPLATE_TEXT_DISPLAY:
            node.text = EDITABLE_TEMPLATE_TEXT_DISPLAY[value]
        elif value not in allowed_template_text:
            raise VerificationError(
                f"PPTX_EDITABLE_TEMPLATE_INVALID:未登记母版提示:{name}:{value}"
            )
    for local in ("rPr", "defRPr", "endParaRPr"):
        for properties in root.iter(f"{{{NS['a']}}}{local}"):
            _normalize_template_run_properties(properties)
    for bullet_font in root.iter(f"{{{NS['a']}}}buFont"):
        bullet_font.attrib["typeface"] = DELIVERY_FONT
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _verify_pptx_themes(archive, names: set[str]) -> dict[str, Any]:
    actual_parts = {name for name in names if re.fullmatch(r"ppt/theme/theme\d+\.xml", name)}
    if actual_parts != THEME_PARTS:
        raise VerificationError("PPTX_THEME_INVALID:主题部件集合不精确")
    font_count = 0
    semantic_hashes: dict[str, str] = {}
    for name in sorted(actual_parts):
        try:
            root = ET.fromstring(archive.read(name))
        except ET.ParseError as exc:
            raise VerificationError(f"PPTX_THEME_INVALID:主题XML无效:{name}") from exc
        if root.tag != f"{{{NS['a']}}}theme" or root.attrib.get("name") != DISPLAY_THEME_NAME:
            raise VerificationError(f"PPTX_THEME_INVALID:主题名称未闭合:{name}")
        for local, expected in DISPLAY_THEME_SCHEME_NAMES.items():
            nodes = list(root.iter(f"{{{NS['a']}}}{local}"))
            if len(nodes) != 1 or nodes[0].attrib.get("name") != expected:
                raise VerificationError(
                    f"PPTX_THEME_INVALID:主题方案名称未闭合:{name}:{local}"
                )
        font_scheme = next(root.iter(f"{{{NS['a']}}}fontScheme"), None)
        if font_scheme is None:
            raise VerificationError(f"PPTX_THEME_INVALID:主题缺少字体方案:{name}")
        fonts = [
            node
            for node in font_scheme.iter()
            if node.tag.rsplit("}", 1)[-1] in {"latin", "ea", "cs", "font"}
        ]
        if not fonts or any(node.attrib.get("typeface") != DELIVERY_FONT for node in fonts):
            raise VerificationError(f"PPTX_THEME_INVALID:主题字体未闭合:{name}")
        font_count += len(fonts)
        digest = _xml_semantic_sha256(root)
        if digest != EXACT_XML_SEMANTIC_SHA256[name]:
            raise VerificationError(f"PPTX_THEME_INVALID:主题结构闭集不精确:{name}")
        semantic_hashes[name] = "sha256:" + digest
    return {
        "status": "complete",
        "part_count": len(actual_parts),
        "font_count": font_count,
        "semantic_sha256": semantic_hashes,
    }


def _verify_pptx_editable_templates(archive, names: set[str]) -> dict[str, Any]:
    actual_parts = {
        name
        for name in names
        if re.fullmatch(
            r"ppt/(?:slideLayouts/slideLayout|slideMasters/slideMaster|notesMasters/notesMaster)\d+\.xml",
            name,
        )
    }
    if actual_parts != EDITABLE_TEMPLATE_PARTS:
        raise VerificationError("PPTX_EDITABLE_TEMPLATE_INVALID:可编辑模板部件集合不精确")
    text_count = 0
    name_count = 0
    run_property_count = 0
    font_count = 0
    allowed_text = set(EDITABLE_TEMPLATE_TEXT_DISPLAY.values())
    allowed_layout_names = set(EDITABLE_LAYOUT_NAME_DISPLAY.values())
    semantic_hashes: dict[str, str] = {}
    for name in sorted(actual_parts):
        try:
            root = ET.fromstring(archive.read(name))
        except ET.ParseError as exc:
            raise VerificationError(
                f"PPTX_EDITABLE_TEMPLATE_INVALID:模板XML无效:{name}"
            ) from exc
        for node in root.iter(f"{{{NS['p']}}}cSld"):
            value = node.attrib.get("name")
            if value is not None and value not in allowed_layout_names:
                raise VerificationError(
                    f"PPTX_EDITABLE_TEMPLATE_INVALID:布局名称未闭合:{name}:{value}"
                )
        for node in root.iter(f"{{{NS['p']}}}cNvPr"):
            value = node.attrib.get("name", "")
            if value and _editable_placeholder_name(value) != value:
                raise VerificationError(
                    f"PPTX_EDITABLE_TEMPLATE_INVALID:占位符名称未闭合:{name}:{value}"
                )
            if value:
                name_count += 1
        for node in root.iter(f"{{{NS['a']}}}t"):
            value = node.text or ""
            if value not in allowed_text:
                raise VerificationError(
                    f"PPTX_EDITABLE_TEMPLATE_INVALID:模板提示未闭合:{name}:{value}"
                )
            text_count += 1
        for node in root.iter():
            if "lang" in node.attrib and node.attrib["lang"] != "zh-CN":
                raise VerificationError(
                    f"PPTX_EDITABLE_TEMPLATE_INVALID:模板语言未闭合:{name}"
                )
        for local in ("rPr", "defRPr", "endParaRPr"):
            for properties in root.iter(f"{{{NS['a']}}}{local}"):
                run_property_count += 1
                if properties.attrib.get("lang") != "zh-CN":
                    raise VerificationError(
                        f"PPTX_EDITABLE_TEMPLATE_INVALID:模板默认语言缺失:{name}"
                    )
                for font_local in ("latin", "ea", "cs"):
                    nodes = list(properties.findall(f"{{{NS['a']}}}{font_local}"))
                    if len(nodes) != 1 or nodes[0].attrib.get("typeface") != DELIVERY_FONT:
                        raise VerificationError(
                            f"PPTX_EDITABLE_TEMPLATE_INVALID:模板默认字体未闭合:{name}:{font_local}"
                        )
                    font_count += 1
        for bullet_font in root.iter(f"{{{NS['a']}}}buFont"):
            if bullet_font.attrib.get("typeface") != DELIVERY_FONT:
                raise VerificationError(
                    f"PPTX_EDITABLE_TEMPLATE_INVALID:项目符号字体未闭合:{name}"
                )
            font_count += 1
        digest = _xml_semantic_sha256(root)
        if digest != EXACT_XML_SEMANTIC_SHA256[name]:
            raise VerificationError(
                f"PPTX_EDITABLE_TEMPLATE_INVALID:模板结构闭集不精确:{name}"
            )
        semantic_hashes[name] = "sha256:" + digest
    if not text_count or not name_count or not run_property_count:
        raise VerificationError("PPTX_EDITABLE_TEMPLATE_INVALID:模板闭合计数异常")
    return {
        "status": "complete",
        "part_count": len(actual_parts),
        "text_count": text_count,
        "named_object_count": name_count,
        "run_property_count": run_property_count,
        "font_count": font_count,
        "semantic_sha256": semantic_hashes,
    }


def _verify_pptx_notes(archive, names, slides: list[str], delivery_ir: dict[str, Any]) -> None:
    """Speaker notes are customer-visible in presenter and print-notes views,
    so they carry the same closed-label, language and typeface obligations as
    slide chrome.  Every notes part in the package must be claimed by exactly
    one slide: an orphan or duplicate notes part is unreviewed customer-visible
    text."""
    notes_type = (
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide"
    )
    present_notes = {
        name
        for name in names
        if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", name)
    }
    claimed_notes: dict[str, int] = {}
    for position, (slide_name, ir_slide) in enumerate(zip(slides, delivery_ir["slides"])):
        index = position + 1
        stem = slide_name.rsplit("/", 1)[-1]
        rels_name = f"ppt/slides/_rels/{stem}.rels"
        if rels_name not in names:
            raise VerificationError(f"PPTX_NOTES_INVALID:第{index}页缺少关系部件")
        try:
            rels_root = ET.fromstring(archive.read(rels_name))
        except ET.ParseError as exc:
            raise VerificationError(
                f"PPTX_NOTES_INVALID:第{index}页关系部件无法解析"
            ) from exc
        targets = [
            node.attrib["Target"]
            for node in rels_root
            if node.attrib.get("Type") == notes_type
        ]
        if len(targets) != 1:
            raise VerificationError(
                f"PPTX_NOTES_INVALID:第{index}页备注页关系数量应为1，实际{len(targets)}"
            )
        notes_name = posixpath.normpath(
            posixpath.join(posixpath.dirname(slide_name), targets[0])
        )
        if notes_name not in present_notes:
            raise VerificationError(f"PPTX_NOTES_INVALID:第{index}页备注部件缺失")
        if notes_name in claimed_notes:
            raise VerificationError(
                f"PPTX_NOTES_INVALID:第{index}页与第{claimed_notes[notes_name]}页共用备注部件"
            )
        claimed_notes[notes_name] = index
        try:
            notes_root = ET.fromstring(archive.read(notes_name))
        except ET.ParseError as exc:
            raise VerificationError(f"PPTX_NOTES_INVALID:第{index}页备注XML无效") from exc

        expected_lines = [
            NOTES_SOURCE_HEADING,
            *ir_slide.get("source_refs", []),
            NOTES_BOUNDARY_HEADING,
            NOTES_BOUNDARY_TEXT,
        ]
        # Compare paragraph by paragraph: a flattened compare cannot tell the
        # writer's one-line-per-entry structure from a single collapsed run.
        actual_lines = [
            "".join(node.text or "" for node in paragraph.findall(".//a:t", NS))
            for paragraph in notes_root.findall(".//a:p", NS)
        ]
        if actual_lines != expected_lines:
            raise VerificationError(
                f"PPTX_NOTES_INVALID:第{index}页备注文本与DeliveryIR不一致"
            )
        for line in actual_lines:
            if _contains_legacy_english_chrome(line):
                raise VerificationError(
                    f"PPTX_NOTES_INVALID:第{index}页备注残留英文固定标签"
                )
        # The writer now customizes a:rPr inside notes too, so this part family
        # carries the same ordered-content-model obligation as the slides.
        _verify_openxml_child_order(notes_root, index)
        # Per-run, not an aggregate count: an a:fld may legitimately carry its
        # own a:rPr, so counting rPr against runs lets a bare run ride along.
        for run in notes_root.findall(".//a:r", NS):
            properties = run.find("a:rPr", NS)
            if properties is None or properties.attrib.get("lang") != "zh-CN":
                raise VerificationError(
                    f"PPTX_NOTES_INVALID:第{index}页备注文字未标记简体中文"
                )
            for font_tag in ("a:latin", "a:ea", "a:cs"):
                font_node = properties.find(font_tag, NS)
                if font_node is None or font_node.attrib.get("typeface") != DELIVERY_FONT:
                    raise VerificationError(
                        f"PPTX_NOTES_INVALID:第{index}页备注未使用大陆交付字体{DELIVERY_FONT}"
                    )
    orphans = sorted(present_notes - set(claimed_notes))
    if orphans:
        raise VerificationError(
            f"PPTX_NOTES_INVALID:存在未被任何幻灯片引用的备注部件:{orphans[0]}"
        )


def _normalized_metadata(
    name: str, raw: bytes, *, slide_count: int = 0, notes_count: int = 0
) -> bytes:
    if name == "ppt/presentation.xml":
        root = ET.fromstring(raw)
        if root.tag != f"{{{NS['p']}}}presentation":
            raise VerificationError(
                "PPTX_SLIDE_SIZE_INVALID:presentation.xml根节点异常"
            )
        slide_sizes = root.findall("./p:sldSz", NS)
        if len(slide_sizes) != 1:
            raise VerificationError(
                "PPTX_SLIDE_SIZE_INVALID:p:sldSz必须为唯一直接子节点"
            )
        slide_size = slide_sizes[0]
        attributes = slide_size.attrib
        if (
            attributes.get("cx") != CLOSED_PPTX_SLIDE_SIZE["cx"]
            or attributes.get("cy") != CLOSED_PPTX_SLIDE_SIZE["cy"]
        ):
            raise VerificationError(
                "PPTX_SLIDE_SIZE_INVALID:canonicalizer不得修改画布尺寸"
            )
        extra_slide_size_attributes = set(attributes) - {"cx", "cy", "type"}
        if extra_slide_size_attributes:
            raise VerificationError(
                "PPTX_SLIDE_SIZE_INVALID:p:sldSz含额外属性"
            )
        if attributes.get("type") not in {None, "screen4x3", "screen16x9"}:
            raise VerificationError(
                "PPTX_SLIDE_SIZE_INVALID:p:sldSz含未知type漂移"
            )
        changed = attributes != CLOSED_PPTX_SLIDE_SIZE
        if changed:
            # cx/cy are already exact; only the known template type drift is
            # safe to repair.  Geometry is never rewritten here.
            slide_size.set("type", CLOSED_PPTX_SLIDE_SIZE["type"])

        style_nodes = root.findall("./p:defaultTextStyle", NS)
        if len(style_nodes) != 1:
            raise VerificationError(
                "PPTX_DEFAULT_TEXT_STYLE_INVALID:p:defaultTextStyle必须唯一"
            )
        style = style_nodes[0]
        default_paragraphs = style.findall("./a:defPPr", NS)
        if len(default_paragraphs) != 1:
            raise VerificationError(
                "PPTX_DEFAULT_TEXT_STYLE_INVALID:a:defPPr必须唯一"
            )
        default_runs = default_paragraphs[0].findall("./a:defRPr", NS)
        if len(default_runs) != 1:
            raise VerificationError(
                "PPTX_DEFAULT_TEXT_STYLE_INVALID:默认a:defRPr必须唯一"
            )
        default_run = default_runs[0]
        if default_run.attrib.get("lang") not in {None, "en-US", "zh-CN"}:
            raise VerificationError(
                "PPTX_DEFAULT_TEXT_STYLE_INVALID:默认语言含未知漂移"
            )
        if default_run.attrib.get("lang") != "zh-CN":
            default_run.set("lang", "zh-CN")
            changed = True

        for level in range(1, 10):
            paragraphs = style.findall(f"./a:lvl{level}pPr", NS)
            if len(paragraphs) != 1:
                raise VerificationError(
                    f"PPTX_DEFAULT_TEXT_STYLE_INVALID:第{level}级段落属性必须唯一"
                )
            runs = paragraphs[0].findall("./a:defRPr", NS)
            if len(runs) != 1:
                raise VerificationError(
                    f"PPTX_DEFAULT_TEXT_STYLE_INVALID:第{level}级defRPr必须唯一"
                )
            run = runs[0]
            if run.attrib.get("lang") not in {None, "en-US", "zh-CN"}:
                raise VerificationError(
                    f"PPTX_DEFAULT_TEXT_STYLE_INVALID:第{level}级语言含未知漂移"
                )
            if run.attrib.get("lang") != "zh-CN":
                run.set("lang", "zh-CN")
                changed = True

            font_nodes: list[ET.Element] = []
            for local, template_value in (
                ("latin", "+mn-lt"),
                ("ea", "+mn-ea"),
                ("cs", "+mn-cs"),
            ):
                nodes = run.findall(f"./a:{local}", NS)
                if len(nodes) > 1:
                    raise VerificationError(
                        f"PPTX_DEFAULT_TEXT_STYLE_INVALID:第{level}级{local}重复"
                    )
                if not nodes:
                    node = ET.Element(f"{{{NS['a']}}}{local}")
                    font_nodes.append(node)
                    changed = True
                else:
                    node = nodes[0]
                    if set(node.attrib) != {"typeface"} or node.attrib.get(
                        "typeface"
                    ) not in {template_value, DELIVERY_FONT}:
                        raise VerificationError(
                            f"PPTX_DEFAULT_TEXT_STYLE_INVALID:第{level}级{local}含未知字体漂移"
                        )
                    font_nodes.append(node)
                    if node.attrib.get("typeface") != DELIVERY_FONT:
                        changed = True
                node.attrib.clear()
                node.set("typeface", DELIVERY_FONT)

            current_children = list(run)
            current_font_order = [
                child.tag.rsplit("}", 1)[-1]
                for child in current_children
                if child.tag.rsplit("}", 1)[-1] in {"latin", "ea", "cs"}
            ]
            if current_font_order != ["latin", "ea", "cs"]:
                changed = True
            for node in font_nodes:
                if node in list(run):
                    run.remove(node)
            tail_locals = {"sym", "hlinkClick", "hlinkMouseOver", "rtl", "extLst"}
            insertion_index = next(
                (
                    index
                    for index, child in enumerate(list(run))
                    if child.tag.rsplit("}", 1)[-1] in tail_locals
                ),
                len(run),
            )
            for offset, node in enumerate(font_nodes):
                run.insert(insertion_index + offset, node)

        if _xml_semantic_sha256(style) != DEFAULT_TEXT_STYLE_SEMANTIC_SHA256:
            raise VerificationError(
                "PPTX_DEFAULT_TEXT_STYLE_INVALID:九级默认文本样式骨架不在精确闭集"
            )
        if not changed:
            return raw
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if name == "docProps/core.xml":
        root = ET.fromstring(raw)
        creator = root.find("dc:creator", CORE_NS)
        modified_by = root.find("cp:lastModifiedBy", CORE_NS)
        created = root.find("dcterms:created", CORE_NS)
        modified = root.find("dcterms:modified", CORE_NS)
        if creator is not None:
            creator.text = "诉讼可视化交付工具"
        if modified_by is not None:
            modified_by.text = "诉讼可视化交付工具"
        if created is not None:
            created.text = "2000-01-01T00:00:00Z"
        if modified is not None:
            modified.text = "2000-01-01T00:00:00Z"
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if name == "docProps/app.xml":
        root = ET.fromstring(raw)
        for tag in ("Company", "Manager"):
            node = root.find(f"{{{APP_NS}}}{tag}")
            if node is not None:
                node.text = ""
        application = root.find(f"{{{APP_NS}}}Application")
        if application is not None:
            application.text = "诉讼可视化交付工具"
        presentation_format = root.find(f"{{{APP_NS}}}PresentationFormat")
        if presentation_format is not None:
            presentation_format.text = DISPLAY_PRESENTATION_FORMAT
        # python-pptx never rewrites the template's English HeadingPairs /
        # TitlesOfParts, which surface in PowerPoint File-Info; close them to
        # the Simplified-Chinese display map like every other visible label.
        for node in root.iter(f"{{{VT_NS}}}lpstr"):
            if node.text in APP_LPSTR_DISPLAY:
                node.text = APP_LPSTR_DISPLAY[node.text]
        for tag, count in (("Slides", slide_count), ("Notes", notes_count)):
            node = root.find(f"{{{APP_NS}}}{tag}")
            if node is None:
                node = ET.SubElement(root, f"{{{APP_NS}}}{tag}")
            node.text = str(count)
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if re.fullmatch(r"ppt/theme/theme\d+\.xml", name):
        # The theme name is customer-visible in the Design tab; keep the part
        # itself and TitlesOfParts naming the same Simplified-Chinese theme.
        root = ET.fromstring(raw)
        root.attrib["name"] = DISPLAY_THEME_NAME
        for local, display in DISPLAY_THEME_SCHEME_NAMES.items():
            nodes = list(root.iter(f"{{{NS['a']}}}{local}"))
            if len(nodes) != 1:
                raise VerificationError(
                    f"PPTX_THEME_INVALID:主题方案节点数量异常:{name}:{local}"
                )
            nodes[0].attrib["name"] = display
        font_scheme = next(root.iter(f"{{{NS['a']}}}fontScheme"), None)
        if font_scheme is None:
            raise VerificationError(f"PPTX_THEME_INVALID:主题缺少字体方案:{name}")
        for node in font_scheme.iter():
            if node.tag.rsplit("}", 1)[-1] in {"latin", "ea", "cs", "font"}:
                node.attrib["typeface"] = DELIVERY_FONT
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if name in EDITABLE_TEMPLATE_PARTS:
        return _normalized_editable_template(name, raw)
    return raw


def _semantic_part(name: str, raw: bytes) -> bytes:
    if not (name.endswith(".xml") or name.endswith(".rels")):
        return raw
    value = RANDOM_REL_ID_RE.sub(b"RELATIONSHIP_ID", raw)
    value = RANDOM_SHAPE_CREATION_RE.sub(b"{SHAPE_CREATION_ID}", value)
    value = RANDOM_SLIDE_CREATION_RE.sub(b"SLIDE_CREATION_ID", value)
    return value


def _owner_for_relationship_part(name: str) -> str | None:
    if name == "_rels/.rels":
        return None
    marker = "/_rels/"
    if marker not in name or not name.endswith(".rels"):
        raise VerificationError("PPTX relationship部件路径异常")
    prefix, basename = name.split(marker, 1)
    owner = f"{prefix}/{basename[:-5]}"
    if not owner or owner.endswith("/"):
        raise VerificationError("PPTX relationship owner路径异常")
    return owner


def _resolve_internal_target(owner: str | None, target: str) -> str:
    if not target or "?" in target or "#" in target or "\\" in target:
        raise VerificationError("PPTX internal relationship Target异常")
    if target.startswith("/"):
        resolved = posixpath.normpath(target.lstrip("/"))
    else:
        base = "" if owner is None else posixpath.dirname(owner)
        resolved = posixpath.normpath(posixpath.join(base, target))
    if (
        not resolved
        or resolved == "."
        or resolved.startswith("../")
        or resolved.startswith("/")
    ):
        raise VerificationError("PPTX internal relationship发生路径逃逸")
    return resolved


def _namespace_prefixes(raw: bytes, namespace: str) -> list[bytes]:
    pattern = re.compile(
        rb"xmlns:([A-Za-z_][A-Za-z0-9_.-]*)\s*=\s*([\"'])"
        + re.escape(namespace.encode("utf-8"))
        + rb"\2"
    )
    return sorted({match.group(1) for match in pattern.finditer(raw)})


def _replace_namespaced_element_attribute(
    raw: bytes,
    *,
    namespace: str,
    element_local: str,
    attribute_local: str,
    old: str,
    new: str,
    expected: int,
) -> bytes:
    prefixes = _namespace_prefixes(raw, namespace)
    if not prefixes and expected:
        raise VerificationError("PPTX namespace前缀缺失")
    prefix_group = b"(?:" + b"|".join(re.escape(value) for value in prefixes) + b")"
    pattern = re.compile(
        rb"(?P<head><"
        + prefix_group
        + rb":"
        + re.escape(element_local.encode("ascii"))
        + rb"\b[^>]*?\b"
        + re.escape(attribute_local.encode("ascii"))
        + rb"\s*=\s*(?P<quote>[\"']))"
        + re.escape(old.encode("utf-8"))
        + rb"(?P=quote)"
    )
    matches = list(pattern.finditer(raw))
    if len(matches) != expected:
        raise VerificationError("PPTX namespaced attribute替换计数异常")
    return pattern.sub(
        lambda match: match.group("head")
        + new.encode("utf-8")
        + match.group("quote"),
        raw,
    )


def _replace_owner_relationship_references(
    raw: bytes, mapping: dict[str, str]
) -> bytes:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise VerificationError("PPTX relationship owner XML无效") from exc
    references = Counter(
        value
        for element in root.iter()
        for attribute, value in element.attrib.items()
        if attribute.startswith(f"{{{NS['r']}}}")
    )
    unknown = sorted(set(references) - set(mapping))
    if unknown:
        raise VerificationError("PPTX relationship owner含悬空引用")
    updated = raw
    prefixes = _namespace_prefixes(updated, NS["r"])
    if references and not prefixes:
        raise VerificationError("PPTX relationship namespace前缀缺失")
    prefix_group = b"(?:" + b"|".join(re.escape(value) for value in prefixes) + b")"
    for old, new in mapping.items():
        if references[old]:
            pattern = re.compile(
                rb"(?P<head>"
                + prefix_group
                + rb":[A-Za-z_][A-Za-z0-9_.-]*\s*=\s*(?P<quote>[\"']))"
                + re.escape(old.encode("utf-8"))
                + rb"(?P=quote)"
            )
            matches = list(pattern.finditer(updated))
            if len(matches) != references[old]:
                raise VerificationError("PPTX relationship owner替换计数异常")
            updated = pattern.sub(
                lambda match: match.group("head")
                + new.encode("utf-8")
                + match.group("quote"),
                updated,
            )
    try:
        checked = ET.fromstring(updated)
    except ET.ParseError as exc:
        raise VerificationError("PPTX relationship owner重写后XML无效") from exc
    rewritten = {
        value
        for element in checked.iter()
        for attribute, value in element.attrib.items()
        if attribute.startswith(f"{{{NS['r']}}}")
    }
    if not rewritten.issubset(set(mapping.values())):
        raise VerificationError("PPTX relationship owner重写闭包失败")
    return updated


def _canonicalize_relationships(payload: dict[str, bytes]) -> None:
    relationship_tag = f"{{{PACKAGE_REL_NS}}}Relationship"
    root_tag = f"{{{PACKAGE_REL_NS}}}Relationships"
    for name in sorted(part for part in payload if part.endswith(".rels")):
        try:
            root = ET.fromstring(payload[name])
        except ET.ParseError as exc:
            raise VerificationError("PPTX relationship XML无效") from exc
        if root.tag != root_tag or root.attrib or (root.text or "").strip():
            raise VerificationError("PPTX relationship根节点超出封闭契约")
        owner = _owner_for_relationship_part(name)
        relations: list[tuple[tuple[str, str, str], str]] = []
        source_ids: set[str] = set()
        for node in list(root):
            if (
                node.tag != relationship_tag
                or set(node.attrib) - RELATIONSHIP_ATTRS
                or list(node)
                or (node.text or "").strip()
                or (node.tail or "").strip()
            ):
                raise VerificationError("PPTX relationship节点超出封闭契约")
            old_id = node.attrib.get("Id", "")
            relation_type = node.attrib.get("Type", "")
            target = node.attrib.get("Target", "")
            target_mode = node.attrib.get("TargetMode", "")
            if not old_id or not relation_type or not target or old_id in source_ids:
                raise VerificationError("PPTX relationship标识或字段异常")
            if target_mode not in {"", "Internal"}:
                raise VerificationError("PPTX含外部relationship")
            resolved = _resolve_internal_target(owner, target)
            if resolved not in payload:
                raise VerificationError("PPTX internal relationship Target不存在")
            source_ids.add(old_id)
            relations.append(((relation_type, target_mode, target), old_id))
        semantic_keys = [key for key, _ in relations]
        if len(semantic_keys) != len(set(semantic_keys)):
            raise VerificationError("PPTX含重复语义relationship")
        ordered = sorted(relations)
        mapping = {
            old_id: f"rId{index:04d}"
            for index, (_key, old_id) in enumerate(ordered, start=1)
        }
        if owner is not None:
            if owner not in payload or not owner.endswith((".xml", ".rels")):
                raise VerificationError("PPTX relationship owner缺失或非XML")
            payload[owner] = _replace_owner_relationship_references(
                payload[owner], mapping
            )
        chunks = [
            '<?xml version="1.0" encoding="utf-8"?>',
            f'<Relationships xmlns="{PACKAGE_REL_NS}">',
        ]
        by_id = {old_id: key for key, old_id in relations}
        for _key, old_id in ordered:
            relation_type, target_mode, target = by_id[old_id]
            attributes = (
                f" Id={quoteattr(mapping[old_id])}"
                f" Type={quoteattr(relation_type)}"
                f" Target={quoteattr(target)}"
            )
            if target_mode:
                attributes += f" TargetMode={quoteattr(target_mode)}"
            chunks.append(f"<Relationship{attributes} />")
        chunks.append("</Relationships>")
        payload[name] = "".join(chunks).encode("utf-8")


def _canonicalize_creation_ids(payload: dict[str, bytes]) -> None:
    shape_values: set[str] = set()
    deterministic_shapes: set[str] = set()
    slide_names = sorted(
        (
            name
            for name in payload
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
        ),
        key=lambda value: int(re.search(r"\d+", value).group(0)),
    )
    used_p14_values: set[int] = set()
    p14_owner_allowlist = (
        re.compile(r"ppt/slides/slide\d+\.xml"),
        re.compile(r"ppt/slideMasters/slideMaster\d+\.xml"),
        re.compile(r"ppt/slideLayouts/slideLayout\d+\.xml"),
        re.compile(r"ppt/notesMasters/notesMaster\d+\.xml"),
    )
    for name in sorted(part for part in payload if part.endswith(".xml")):
        raw = payload[name]
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise VerificationError("PPTX XML部件无效") from exc
        parents = {child: parent for parent in root.iter() for child in parent}
        shape_nodes = list(root.iter(f"{{{A16_NS}}}creationId"))
        updated = raw
        for node in shape_nodes:
            old = node.attrib.get("id", "")
            try:
                uuid.UUID(old.strip("{}"))
            except (ValueError, AttributeError) as exc:
                raise VerificationError("PPTX a16 creationId格式异常") from exc
            if old in shape_values:
                raise VerificationError("PPTX a16 creationId源值重复")
            shape_values.add(old)
            owner = parents.get(node)
            while owner is not None and owner.tag.rsplit("}", 1)[-1] != "cNvPr":
                owner = parents.get(owner)
            if owner is None:
                raise VerificationError("PPTX a16 creationId位于未知上下文")
            object_id = owner.attrib.get("id", "").strip()
            object_name = owner.attrib.get("name", "")
            if not object_id:
                raise VerificationError("PPTX a16 creationId缺少cNvPr稳定键")
            stable_key = f"{name}|cNvPr|{object_id}|{object_name}"
            new = "{" + str(
                uuid.uuid5(DETERMINISTIC_UUID_NAMESPACE, stable_key)
            ).upper() + "}"
            if new in deterministic_shapes:
                raise VerificationError("PPTX a16 creationId确定性碰撞")
            deterministic_shapes.add(new)
            updated = _replace_namespaced_element_attribute(
                updated,
                namespace=A16_NS,
                element_local="creationId",
                attribute_local="id",
                old=old,
                new=new,
                expected=1,
            )

        slide_nodes = list(root.iter(f"{{{P14_NS}}}creationId"))
        is_slide = name in slide_names
        is_allowed_owner = any(pattern.fullmatch(name) for pattern in p14_owner_allowlist)
        # python-pptx 1.0.2 emits one p14 creationId on its master/layout
        # owners but none on newly-created slides.  Bind every observed ID to
        # an explicit owner allowlist and require exactly one per owner; a
        # slide with zero remains the valid portable representation.
        if slide_nodes and (not is_allowed_owner or len(slide_nodes) != 1):
            raise VerificationError("PPTX p14 creationId位于未知上下文或计数异常")
        if is_slide and len(slide_nodes) > 1:
            raise VerificationError("PPTX p14 creationId位于未知上下文或计数异常")
        if slide_nodes:
            old = slide_nodes[0].attrib.get("val", "")
            if not old.isdigit() or not 0 <= int(old) <= 0xFFFFFFFF:
                raise VerificationError("PPTX p14 creationId格式异常")
            salt = 0
            while True:
                digest = hashlib.sha256(
                    f"{name}|p14|{salt}".encode("utf-8")
                ).digest()
                value = int.from_bytes(digest[:4], "big") & 0x7FFFFFFF
                value = value or 1
                if value not in used_p14_values:
                    break
                salt += 1
            used_p14_values.add(value)
            updated = _replace_namespaced_element_attribute(
                updated,
                namespace=P14_NS,
                element_local="creationId",
                attribute_local="val",
                old=old,
                new=str(value),
                expected=1,
            )
        payload[name] = updated


def normalize_pptx(path: Path) -> str:
    """Canonicalize closed OOXML for portable raw-byte identity."""

    if not _regular_file(path):
        raise VerificationError("待规范化PPTX缺失")
    try:
        with zipfile.ZipFile(path) as source:
            infos = _safe_zip_members(source)
            slide_count = sum(
                1
                for info in infos
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", info.filename)
            )
            notes_count = sum(
                1
                for info in infos
                if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", info.filename)
            )
            payload = {
                info.filename: _normalized_metadata(
                    info.filename,
                    source.read(info),
                    slide_count=slide_count,
                    notes_count=notes_count,
                )
                for info in infos
                if not info.is_dir()
            }
            _canonicalize_relationships(payload)
            _canonicalize_creation_ids(payload)
    except (OSError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise VerificationError("PPTX确定性规范化失败") from exc
    temp: Path | None = None
    try:
        fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".normalized", dir=path.parent)
        os.close(fd)
        temp = Path(raw_temp)
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as target:
            for name in sorted(payload):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100600 << 16
                target.writestr(info, payload[name])
        with temp.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temp, path)
        temp = None
    finally:
        if temp is not None:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
    structure = hashlib.sha256()
    for name in sorted(payload):
        structure.update(
            name.encode("utf-8")
            + b"\x00"
            + _semantic_part(name, payload[name])
            + b"\x00"
        )
    return structure.hexdigest()


def _verify_pptx_slide_size(archive: zipfile.ZipFile) -> dict[str, Any]:
    """Independently close the final presentation size and its 16:9 meaning."""

    try:
        root = ET.fromstring(archive.read("ppt/presentation.xml"))
    except (KeyError, ET.ParseError) as exc:
        raise VerificationError(
            "PPTX_SLIDE_SIZE_INVALID:presentation.xml缺失或XML无效"
        ) from exc
    if root.tag != f"{{{NS['p']}}}presentation":
        raise VerificationError("PPTX_SLIDE_SIZE_INVALID:presentation.xml根节点异常")
    slide_sizes = root.findall("./p:sldSz", NS)
    if len(slide_sizes) != 1:
        raise VerificationError(
            "PPTX_SLIDE_SIZE_INVALID:p:sldSz必须为唯一直接子节点"
        )
    attributes = slide_sizes[0].attrib
    if attributes != CLOSED_PPTX_SLIDE_SIZE:
        raise VerificationError(
            "PPTX_SLIDE_SIZE_INVALID:p:sldSz属性不等于16:9闭集"
        )
    cx = int(attributes["cx"])
    cy = int(attributes["cy"])
    if cx * 9 != cy * 16:
        raise VerificationError("PPTX_SLIDE_SIZE_INVALID:p:sldSz数值比例不是16:9")
    return {
        "status": "complete",
        "cx": cx,
        "cy": cy,
        "aspect_ratio": "16:9",
        "type": attributes["type"],
    }


def _verify_pptx_default_text_style(archive: zipfile.ZipFile) -> dict[str, Any]:
    """Verify the final presentation defaults without trusting normalization."""

    try:
        root = ET.fromstring(archive.read("ppt/presentation.xml"))
    except (KeyError, ET.ParseError) as exc:
        raise VerificationError(
            "PPTX_DEFAULT_TEXT_STYLE_INVALID:presentation.xml缺失或XML无效"
        ) from exc
    style_nodes = root.findall("./p:defaultTextStyle", NS)
    if len(style_nodes) != 1:
        raise VerificationError(
            "PPTX_DEFAULT_TEXT_STYLE_INVALID:p:defaultTextStyle必须唯一"
        )
    style = style_nodes[0]
    semantic_sha256 = _xml_semantic_sha256(style)
    if semantic_sha256 != DEFAULT_TEXT_STYLE_SEMANTIC_SHA256:
        raise VerificationError(
            "PPTX_DEFAULT_TEXT_STYLE_INVALID:九级默认文本样式语义指纹不匹配"
        )
    default_paragraphs = style.findall("./a:defPPr", NS)
    if len(default_paragraphs) != 1:
        raise VerificationError("PPTX_DEFAULT_TEXT_STYLE_INVALID:a:defPPr必须唯一")
    default_runs = default_paragraphs[0].findall("./a:defRPr", NS)
    if len(default_runs) != 1 or default_runs[0].attrib.get("lang") != "zh-CN":
        raise VerificationError(
            "PPTX_DEFAULT_TEXT_STYLE_INVALID:默认defRPr语言不是zh-CN"
        )

    font_slot_count = 0
    for level in range(1, 10):
        paragraphs = style.findall(f"./a:lvl{level}pPr", NS)
        if len(paragraphs) != 1:
            raise VerificationError(
                f"PPTX_DEFAULT_TEXT_STYLE_INVALID:第{level}级段落属性必须唯一"
            )
        runs = paragraphs[0].findall("./a:defRPr", NS)
        if len(runs) != 1 or runs[0].attrib.get("lang") != "zh-CN":
            raise VerificationError(
                f"PPTX_DEFAULT_TEXT_STYLE_INVALID:第{level}级defRPr语言不是zh-CN"
            )
        run = runs[0]
        font_nodes: list[ET.Element] = []
        for local in ("latin", "ea", "cs"):
            nodes = run.findall(f"./a:{local}", NS)
            if len(nodes) != 1 or nodes[0].attrib != {"typeface": DELIVERY_FONT}:
                raise VerificationError(
                    f"PPTX_DEFAULT_TEXT_STYLE_INVALID:第{level}级{local}字体不闭合"
                )
            font_nodes.append(nodes[0])
            font_slot_count += 1
        indexes = [list(run).index(node) for node in font_nodes]
        if indexes != sorted(indexes):
            raise VerificationError(
                f"PPTX_DEFAULT_TEXT_STYLE_INVALID:第{level}级字体节点顺序异常"
            )
    return {
        "status": "complete",
        "skeleton": "exact",
        "semantic_sha256": "sha256:" + semantic_sha256,
        "language": "zh-CN",
        "level_count": 9,
        "run_properties_count": 10,
        "font_slot_count": font_slot_count,
        "typeface": DELIVERY_FONT,
    }


def verify_pptx(path: Path, delivery_ir: dict[str, Any], *, structure_sha256: str | None = None) -> dict[str, Any]:
    if not _regular_file(path) or path.stat().st_size < 1024:
        raise VerificationError("PPTX缺失、非普通文件或过小")
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise VerificationError("PPTX不是有效ZIP") from exc
    with archive:
        infos = _safe_zip_members(archive)
        names = {info.filename for info in infos}
        required = {"[Content_Types].xml", "ppt/presentation.xml"}
        if not required.issubset(names):
            raise VerificationError("PPTX缺少必要OOXML部件")
        app_props = names.intersection({"docProps/app.xml"})
        if not app_props:
            raise VerificationError("PPTX缺少docProps/app.xml")
        lowered_names = [name.lower() for name in names]
        if any(
            fragment in name
            for name in lowered_names
            for fragment in FORBIDDEN_MEMBER_FRAGMENTS
        ):
            raise VerificationError("PPTX含宏、OLE、评论或隐藏扩展部件")
        slides = sorted(
            (
                name
                for name in names
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
            ),
            key=lambda value: int(re.search(r"\d+", value).group(0)),
        )
        if len(slides) != len(delivery_ir["slides"]):
            raise VerificationError("PPTX页数与DeliveryIR不一致")
        notes_count = sum(
            1
            for name in names
            if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", name)
        )
        try:
            app_root = ET.fromstring(archive.read("docProps/app.xml"))
            slides_node = app_root.find(f"{{{APP_NS}}}Slides")
            notes_node = app_root.find(f"{{{APP_NS}}}Notes")
            if (
                slides_node is None
                or slides_node.text != str(len(slides))
                or notes_node is None
                or notes_node.text != str(notes_count)
            ):
                raise VerificationError("PPTX app.xml Slides/Notes计数不准确")
        except ET.ParseError as exc:
            raise VerificationError("PPTX app.xml无效") from exc
        all_bytes = bytearray()
        external_relationships = False
        slide_metrics: list[dict[str, Any]] = []
        rendered_semantic_ids: list[str] = []
        typography_role_counts: Counter[str] = Counter()
        typography_minimum_points: dict[str, float] = {}
        timeline_indexes = [
            index
            for index, slide in enumerate(delivery_ir["slides"])
            if slide["role"] == "timeline"
        ]
        undated_timeline_indexes = [
            index
            for index in timeline_indexes
            if delivery_ir["slides"][index]["content"]["undated_milestones"]
        ]
        if undated_timeline_indexes and undated_timeline_indexes != timeline_indexes[
            -len(undated_timeline_indexes) :
        ]:
            raise VerificationError(
                "TIMELINE_LAYOUT_INVALID:未定日期事项必须形成连续末尾页"
            )
        for info in infos:
            if info.is_dir():
                continue
            raw = archive.read(info)
            if len(raw) != info.file_size:
                raise VerificationError("PPTX ZIP成员读取长度不符")
            # The package-level uncompressed-size gate caps this aggregate at
            # 80 MiB, so scan every byte of notes, docProps, alt text and other
            # OOXML parts rather than sampling prefixes.
            all_bytes.extend(raw)
            if info.filename.endswith(".rels") and b'TargetMode="External"' in raw:
                external_relationships = True
        if external_relationships:
            raise VerificationError("PPTX含外部relationship")
        for marker in FORBIDDEN_TEXT:
            if marker.lower() in bytes(all_bytes).lower():
                raise VerificationError("PPTX隐私扫描命中内部路径或canary")
        # Runs after the structural and privacy scans so a malformed or
        # canary-bearing package is still reported by its own gate first.
        slide_size_closure = _verify_pptx_slide_size(archive)
        default_text_style_closure = _verify_pptx_default_text_style(archive)
        doc_properties_closure = _verify_pptx_document_properties(
            archive, slide_count=len(slides), notes_count=notes_count
        )
        theme_closure = _verify_pptx_themes(archive, names)
        editable_template_closure = _verify_pptx_editable_templates(archive, names)
        _verify_pptx_notes(archive, names, slides, delivery_ir)
        for index, (slide_name, ir_slide) in enumerate(zip(slides, delivery_ir["slides"])):
            try:
                root = ET.fromstring(archive.read(slide_name))
            except ET.ParseError as exc:
                raise VerificationError(f"PPTX第{index + 1}页XML无效") from exc
            visible_slide_text = "".join(
                node.text or "" for node in root.findall(".//a:t", NS)
            )
            if (
                delivery_ir.get("release_state") == "REVIEW_DRAFT"
                and DISPLAY_REVIEW_STATE not in visible_slide_text
            ):
                raise VerificationError(
                    f"PPTX第{index + 1}页缺少可见中文审阅稿标识"
                )
            text_typography = _verify_ooxml_text_roles(root, index + 1)
            openxml_schema_order = _verify_openxml_child_order(root, index + 1)
            visible_object_ledger = _verify_pptx_visible_object_ledger(
                root, delivery_ir, ir_slide, index
            )
            typography_role_counts.update(text_typography["role_counts"])
            for text_role, actual_points in text_typography[
                "minimum_actual_points"
            ].items():
                typography_minimum_points[text_role] = min(
                    typography_minimum_points.get(text_role, actual_points),
                    actual_points,
                )
            shape_count = len(root.findall(".//p:sp", NS))
            connector_count = len(root.findall(".//p:cxnSp", NS))
            table_count = len(root.findall(".//a:tbl", NS))
            picture_count = len(root.findall(".//p:pic", NS))
            for paragraph in root.findall(".//a:p", NS):
                paragraph_text = "".join(
                    node.text or "" for node in paragraph.findall(".//a:t", NS)
                )
                if not CJK_RE.search(paragraph_text):
                    continue
                for properties in (
                    paragraph.findall(".//a:rPr", NS)
                    + paragraph.findall(".//a:defRPr", NS)
                ):
                    latin = properties.find("a:latin", NS)
                    east_asian = properties.find("a:ea", NS)
                    if (
                        latin is None
                        or not latin.attrib.get("typeface", "").strip()
                        or east_asian is None
                        or not east_asian.attrib.get("typeface", "").strip()
                    ):
                        raise VerificationError(
                            f"PPTX第{index + 1}页中文run缺失显式latin/ea字体"
                        )
            for node in root.iter():
                if node.tag.rsplit("}", 1)[-1] == "cNvPr":
                    rendered_semantic_ids.extend(
                        SEMANTIC_NAME_RE.findall(node.attrib.get("name", ""))
                    )
            if shape_count < 2:
                raise VerificationError(f"PPTX第{index + 1}页缺少原生文本/形状")
            if picture_count:
                raise VerificationError(f"PPTX第{index + 1}页含图片；S2首轮不允许截图主内容")
            role = ir_slide["role"]
            timeline_layout = None
            relationship_layout = None
            if role == "relationship":
                if connector_count != 0:
                    raise VerificationError(
                        "PPTX关系页含未授权connector；DeliveryIR v1不含显式edges"
                    )
                relationship_layout = _verify_relationship_layout(
                    root, ir_slide["slide_id"], ir_slide["content"]
                )
            if role == "timeline":
                if (
                    ir_slide["content"]["undated_milestones"]
                    and ir_slide["content"]["events"]
                ):
                    raise VerificationError(
                        "TIMELINE_LAYOUT_INVALID:未定日期事项不得与日期事件混页"
                    )
                timeline_layout = _verify_timeline_layout(
                    root, ir_slide["slide_id"], ir_slide["content"]
                )
            if role in {"evidence_matrix", "stage_risk"}:
                has_rows = any(
                    ir_slide["content"].get(key)
                    for key in ("rows", "amounts", "stages", "risks")
                )
                if has_rows and table_count < 1:
                    raise VerificationError("PPTX矩阵/阶段页未生成原生table")
            slide_metrics.append(
                {
                    "slide": index + 1,
                    "role": role,
                    "shapes": shape_count,
                    "connectors": connector_count,
                    "tables": table_count,
                    "pictures": picture_count,
                    "text_typography": text_typography,
                    "openxml_schema_order": openxml_schema_order,
                    "visible_object_ledger": visible_object_ledger,
                    "relationship_layout": relationship_layout,
                    "timeline_layout": timeline_layout,
                }
            )
    try:
        semantic_completeness = compare_rendered_inventory(
            delivery_ir, rendered_semantic_ids, artifact_format="pptx"
        )
    except SemanticInventoryError as exc:
        raise VerificationError(str(exc)) from exc
    return {
        "format": "pptx",
        "sha256": _sha256(path),
        "structure_sha256": structure_sha256 or "",
        "determinism_mode": "python_pptx_1_0_2_canonical_zip_raw_byte_identical",
        "size_bytes": path.stat().st_size,
        "slide_count": len(delivery_ir["slides"]),
        "native_editability": "pass",
        "external_relationships": False,
        "macros_or_ole": False,
        "review_draft_visible_on_all_slides": True,
        "privacy_scan": {
            "status": "pass",
            "scopes": [
                "all_package_parts",
                "slide_text",
                "shape_names_and_alt_text",
                "speaker_notes",
                "document_properties",
                "relationships",
            ],
            "forbidden_markers": "absent",
        },
        "text_typography": {
            "status": "pass",
            "authority": "final_ooxml_a:rPr_sz",
            "minimum_required_points": {
                role: value / 100
                for role, value in TEXT_ROLE_MINIMUM_HUNDREDTH_POINTS.items()
            },
            "role_counts": dict(sorted(typography_role_counts.items())),
            "minimum_actual_points": dict(sorted(typography_minimum_points.items())),
        },
        "visible_object_ledger": {
            "status": "complete",
            "slide_count": len(slide_metrics),
            "object_count": sum(
                item["visible_object_ledger"]["object_count"]
                for item in slide_metrics
            ),
            "text_object_count": sum(
                item["visible_object_ledger"]["text_object_count"]
                for item in slide_metrics
            ),
            "extra_object_count": 0,
            "rewritten_text_object_count": 0,
        },
        "openxml_schema_order": {
            "status": "pass",
            "run_properties_checked": sum(
                item["openxml_schema_order"]["run_properties_checked"]
                for item in slide_metrics
            ),
            "table_cell_properties_checked": sum(
                item["openxml_schema_order"]["table_cell_properties_checked"]
                for item in slide_metrics
            ),
        },
        "slide_size_closure": slide_size_closure,
        "default_text_style_closure": default_text_style_closure,
        "doc_properties_closure": doc_properties_closure,
        "theme_closure": theme_closure,
        "editable_template_closure": editable_template_closure,
        "slide_metrics": slide_metrics,
        "semantic_completeness": semantic_completeness,
    }


class _VisibleTextLedgerParser(HTMLParser):
    """Fail-closed reverse inventory for every article text occurrence."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, Any]] = []
        self.articles: list[dict[str, Any]] = []
        self.current_article: dict[str, Any] | None = None
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        frame: dict[str, Any] = {"tag": tag, "owner": None, "article": False}
        if tag == "article" and "slide" in values.get("class", "").split():
            if self.current_article is not None:
                self.errors.append("nested article")
            class_tokens = values.get("class", "").split()
            role_tokens = [
                value.removeprefix("role-")
                for value in class_tokens
                if value.startswith("role-")
            ]
            self.current_article = {
                "owners": [],
                "unregistered": [],
                "classes": class_tokens,
                "role": role_tokens[0] if len(role_tokens) == 1 else "",
                "declared_count": values.get("data-visible-owner-count"),
                "declared_ledger": values.get(
                    "data-visible-owner-ledger-sha256"
                ),
            }
            frame["article"] = True
        semantic_id = values.get("data-semantic-id")
        static_id = values.get("data-static-id")
        visible_hash = values.get("data-visible-text-sha256")
        if semantic_id or static_id:
            if self.current_article is None:
                self.errors.append("visible owner outside article")
            if bool(semantic_id) == bool(static_id) or not visible_hash:
                self.errors.append("invalid visible owner attributes")
            owner = {
                "kind": "semantic" if semantic_id else "static",
                "id": semantic_id or static_id,
                "hash": visible_hash,
                "text": [],
            }
            frame["owner"] = owner
            if self.current_article is not None:
                self.current_article["owners"].append(owner)
        if tag in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            return
        self.stack.append(frame)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return
        if self.current_article is None:
            # CSS and the document title are non-page head content.  Every
            # non-whitespace body text node must be inside a slide article.
            if not any(frame.get("tag") in {"style", "title"} for frame in self.stack):
                self.errors.append("unregistered visible text outside article")
            return
        owners = [frame["owner"] for frame in self.stack if frame.get("owner")]
        if not owners:
            self.current_article["unregistered"].append(data.strip()[:80])
            return
        for owner in owners:
            owner["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack:
            self.errors.append(f"orphan close:{tag}")
            return
        frame = self.stack.pop()
        if frame["tag"] != tag:
            self.errors.append(f"mismatched close:{frame['tag']}:{tag}")
        owner = frame.get("owner")
        if owner is not None:
            actual_text = "".join(owner["text"])
            actual = "sha256:" + hashlib.sha256(
                actual_text.encode("utf-8")
            ).hexdigest()
            owner["actual_text"] = actual_text
            if actual != owner["hash"]:
                self.errors.append(f"visible owner text hash mismatch:{owner['id']}")
        if frame.get("article"):
            article = self.current_article
            if article is None:
                self.errors.append("article close without state")
                return
            owners = article["owners"]
            tokens = [[item["kind"], item["id"], item["hash"]] for item in owners]
            payload = json.dumps(
                tokens, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            actual_ledger = "sha256:" + hashlib.sha256(payload).hexdigest()
            try:
                declared_count = int(article["declared_count"])
            except (TypeError, ValueError):
                declared_count = -1
            if declared_count != len(owners) or article["declared_ledger"] != actual_ledger:
                self.errors.append("article visible owner ledger mismatch")
            static_ids = [item["id"] for item in owners if item["kind"] == "static"]
            if len(static_ids) != len(set(static_ids)):
                self.errors.append("duplicate static visible owner")
            if any(not STATIC_HTML_ID_RE.fullmatch(value) for value in static_ids):
                self.errors.append("unregistered static visible owner")
            if article["unregistered"]:
                self.errors.append("unregistered visible article text")
            self.articles.append(article)
            self.current_article = None


def _expected_html_static_ledger(delivery_ir: dict[str, Any]) -> list[dict[str, Any]]:
    """Rebuild fixed HTML chrome independently of writer/self-declared hashes.

    Each static entry carries its ordinal in the complete semantic+static owner
    stream.  Comparing only the static subsequence would miss moving unchanged
    fixed chrome across a semantic owner.
    """

    slides = delivery_ir.get("slides")
    profile = delivery_ir.get("profile")
    inventory = delivery_ir.get("semantic_inventory")
    if not isinstance(slides, list) or not isinstance(profile, dict) or not isinstance(inventory, list):
        raise VerificationError("HTML_STATIC_LEDGER_INVALID:DeliveryIR缺少闭合字段")
    semantic_locations = {
        (item.get("slide_id"), item.get("slot"), item.get("item_index"))
        for item in inventory
        if isinstance(item, dict)
    }
    table_headers = visible_table_headers(delivery_ir.get("source_schema"))
    result: list[dict[str, Any]] = []

    def text_value(value: Any) -> str:
        if isinstance(value, dict):
            value = value.get("text")
        if not isinstance(value, str):
            raise VerificationError("HTML_STATIC_LEDGER_INVALID:DeliveryIR文本无效")
        return value.strip()

    for position, slide in enumerate(slides):
        if not isinstance(slide, dict) or not isinstance(slide.get("content"), dict):
            raise VerificationError("HTML_STATIC_LEDGER_INVALID:DeliveryIR slide无效")
        slide_id = slide.get("slide_id")
        role = slide.get("role")
        content = slide["content"]
        if not isinstance(slide_id, str) or role not in DISPLAY_ROLE_LABEL_BY_ROLE:
            raise VerificationError("HTML_STATIC_LEDGER_INVALID:DeliveryIR role无效")
        owners: list[dict[str, str] | None] = []

        def semantic(count: int = 1) -> None:
            owners.extend([None] * count)

        def static(static_id: str, value: str) -> None:
            owners.append({"id": static_id, "text": value})

        def semantic_items(slot: str) -> None:
            values = content.get(slot, [])
            if not isinstance(values, list):
                raise VerificationError(
                    f"HTML_STATIC_LEDGER_INVALID:DeliveryIR列表无效:{slide_id}:{slot}"
                )
            semantic(len(values))

        def static_table(slot: str, label: str, header: list[str]) -> None:
            rows = content.get(slot, [])
            if not isinstance(rows, list):
                raise VerificationError(
                    f"HTML_STATIC_LEDGER_INVALID:DeliveryIR表格无效:{slide_id}:{slot}"
                )
            if not rows:
                static(f"{label}:empty", "本节暂无已确认条目。")
                return
            first = rows[0]
            cells = first.get("cells") if isinstance(first, dict) else None
            if not isinstance(cells, list):
                raise VerificationError(
                    f"HTML_STATIC_LEDGER_INVALID:DeliveryIR表格行无效:{slide_id}:{slot}"
                )
            if len(cells) == len(header) and [str(value) for value in cells] != header:
                static(f"{label}:header", "".join(header))
            semantic(len(rows))

        static("watermark:release-state", DISPLAY_REVIEW_STATE)
        if role == "cover":
            # title owner contains the nested matter-label owner, then client.
            semantic(3)
            static(
                "cover-lead",
                "基于已冻结材料整理，用于律师与客户共同复核事实、证据和下一步安排。",
            )
            content_profile = content.get("profile", content)
            if not isinstance(content_profile, dict):
                raise VerificationError("HTML_STATIC_LEDGER_INVALID:cover profile无效")
            merged = dict(profile)
            profile_keys = {key for key, _ in HTML_PROFILE_FIELDS}
            profile_keys.update(
                alias for aliases in HTML_PROFILE_ALIASES.values() for alias in aliases
            )
            profile_keys.update({"title", "document_title", "subtitle"})
            for key in profile_keys:
                if key in content_profile:
                    merged[key] = content_profile[key]

            def profile_value(key: str) -> Any:
                value = merged.get(key)
                if value is not None and value != "":
                    return value
                for alias in HTML_PROFILE_ALIASES.get(key, ()):
                    value = merged.get(alias)
                    if value is not None and value != "":
                        return value
                return None

            for key, label in HTML_PROFILE_FIELDS:
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
                    raise VerificationError(
                        "HTML_STATIC_LEDGER_INVALID:confidentiality缺少简体中文显示映射"
                    )
                static(f"cover-meta-label:{key}", label)
                if (slide_id, f"profile.{key}", 0) in semantic_locations:
                    semantic()
                else:
                    static(f"cover-meta-value:{key}", display)
        else:
            static("header:role-label", DISPLAY_ROLE_LABEL_BY_ROLE[role])
            semantic()  # slide title
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
            raise VerificationError("HTML_STATIC_LEDGER_INVALID:source_refs无效")
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


def _verify_html_visible_text_ledger(
    text: str, expected_articles: int, delivery_ir: dict[str, Any]
) -> dict[str, Any]:
    parser = _VisibleTextLedgerParser()
    try:
        parser.feed(text)
        parser.close()
    except (TypeError, ValueError) as exc:
        raise VerificationError("HTML可见文本账无法解析") from exc
    if parser.current_article is not None or parser.stack:
        parser.errors.append("unclosed HTML structure")
    if len(parser.articles) != expected_articles:
        parser.errors.append("visible ledger article count mismatch")
    expected_static = _expected_html_static_ledger(delivery_ir)
    # The release mark must be anchored per article, not satisfied by a single
    # document-wide substring that source text could supply on its own.
    for position, article in enumerate(parser.articles):
        watermarks = [
            owner
            for owner in article["owners"]
            if owner["kind"] == "static" and owner["id"] == "watermark:release-state"
        ]
        if len(watermarks) != 1:
            parser.errors.append(
                f"article {position + 1} does not carry exactly one release-state watermark owner"
            )
    owners = [owner for article in parser.articles for owner in article["owners"]]
    for owner in owners:
        if owner["kind"] != "static":
            continue
        actual_text = owner.get("actual_text", "")
        if owner["id"] == "watermark:release-state" and actual_text != DISPLAY_REVIEW_STATE:
            parser.errors.append("watermark release state is not Simplified Chinese")
        elif owner["id"] == "footer:document-label" and actual_text != DISPLAY_DOCUMENT_LABEL:
            parser.errors.append("footer document label is not Simplified Chinese")
        elif owner["id"] == "header:role-label" and actual_text not in DISPLAY_ROLE_LABELS:
            parser.errors.append("header role label is outside the Simplified Chinese allowlist")
        if _contains_legacy_english_chrome(actual_text):
            parser.errors.append("static customer chrome contains legacy English label")
    try:
        cover_slide_id = delivery_ir["slides"][0]["slide_id"]
        confidentiality_ids = [
            item["semantic_id"]
            for item in delivery_ir["semantic_inventory"]
            if item.get("slide_id") == cover_slide_id
            and item.get("slot") == "profile.confidentiality"
            and item.get("item_index") == 0
        ]
        if len(confidentiality_ids) != 1:
            raise KeyError("profile.confidentiality semantic locator")
        confidentiality_id = confidentiality_ids[0]
        confidentiality_value = delivery_ir["profile"]["confidentiality"]
        expected_confidentiality = DISPLAY_CONFIDENTIALITY[confidentiality_value]
    except (KeyError, IndexError, TypeError) as exc:
        raise VerificationError("HTML缺少保密级别简体中文显示绑定") from exc
    confidentiality_owners = [
        owner
        for owner in owners
        if owner["kind"] == "semantic" and owner["id"] == confidentiality_id
    ]
    if len(confidentiality_owners) != 1 or confidentiality_owners[0].get("actual_text") != expected_confidentiality:
        parser.errors.append("confidentiality display mapping mismatch")
    if not parser.errors:
        if len(parser.articles) != len(expected_static):
            raise VerificationError("HTML_STATIC_LEDGER_INVALID:页面数量不一致")
        for position, (article, expected) in enumerate(
            zip(parser.articles, expected_static), 1
        ):
            actual_static = [
                {
                    "owner_ordinal": ordinal,
                    "id": owner["id"],
                    "text": owner.get("actual_text", ""),
                }
                for ordinal, owner in enumerate(article["owners"])
                if owner["kind"] == "static"
            ]
            if (
                article.get("role") != expected["role"]
                or article.get("classes")
                != ["slide", f"role-{expected['role']}"]
                or len(article["owners"]) != expected["owner_count"]
                or actual_static != expected["static"]
            ):
                raise VerificationError(
                    f"HTML_STATIC_LEDGER_INVALID:第{position}页static text/location/order不一致"
                )
    if parser.errors:
        raise VerificationError(
            "SILENT_TRUNCATION_DETECTED:HTML存在未登记或被改写的可见文本:"
            + ";".join(parser.errors[:5])
        )
    return {
        "status": "complete",
        "article_count": len(parser.articles),
        "visible_owner_count": sum(
            len(article["owners"]) for article in parser.articles
        ),
        "unregistered_visible_text_count": 0,
        "owner_text_hash_mismatch_count": 0,
        "static_role_ledger_status": "complete",
        "static_role_count": sum(len(item["static"]) for item in expected_static),
        "static_role_ledger_sha256": "sha256:"
        + hashlib.sha256(
            json.dumps(
                expected_static, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
    }


def verify_html(path: Path, delivery_ir: dict[str, Any]) -> dict[str, Any]:
    if not _regular_file(path) or path.stat().st_size < 1024:
        raise VerificationError("HTML缺失、非普通文件或过小")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise VerificationError("HTML不是UTF-8") from exc
    lowered = text.lower()
    style_blocks = re.findall(r"<style>(.*?)</style>", text, flags=re.DOTALL)
    if (
        len(style_blocks) != 1
        or len(re.findall(r"<style\b", text, flags=re.IGNORECASE)) != 1
        or len(re.findall(r"</style\s*>", text, flags=re.IGNORECASE)) != 1
        or hashlib.sha256(style_blocks[0].encode("utf-8")).hexdigest()
        != HTML_STYLE_SHA256
    ):
        raise VerificationError("HTML_STYLESHEET_INVALID:样式表未与闭合集精确一致")
    forbidden = (
        "<script",
        "<link",
        "<!--",
        "-->",
        "javascript:",
        "http://",
        "https://",
        "file://",
        "src=\"//",
        "href=\"//",
        "display: none",
        "visibility: hidden",
        "opacity: 0",
    )
    if any(value in lowered for value in forbidden):
        raise VerificationError("HTML含脚本、外链或隐藏内容")
    if re.search(r"\b(?:hidden|aria-hidden)\b(?:\s|=)", lowered):
        raise VerificationError("HTML含隐藏DOM属性")
    if re.search(r"\sstyle\s*=", lowered):
        raise VerificationError("HTML含未授权内联样式")
    data_attributes = re.findall(r"\b(data-[a-z0-9_.:-]+)\s*=", lowered)
    allowed_data_attributes = {
        "data-semantic-id",
        "data-static-id",
        "data-visible-text-sha256",
        "data-visible-owner-count",
        "data-visible-owner-ledger-sha256",
    }
    if any(name not in allowed_data_attributes for name in data_attributes):
        raise VerificationError("HTML含未授权data属性")
    if "script-src &apos;none&apos;" not in lowered or "connect-src &apos;none&apos;" not in lowered:
        raise VerificationError("HTML缺失离线CSP")
    slide_count = lowered.count('<article class="slide role-')
    if slide_count != len(delivery_ir["slides"]):
        raise VerificationError("HTML页数与DeliveryIR不一致")
    visible_text_ledger = _verify_html_visible_text_ledger(
        text, slide_count, delivery_ir
    )
    if DISPLAY_REVIEW_STATE not in text:
        raise VerificationError("HTML缺少中文审阅稿水印")
    for marker in FORBIDDEN_TEXT:
        if marker.decode("ascii", "ignore").lower() in lowered:
            raise VerificationError("HTML隐私扫描命中内部路径或canary")
    try:
        semantic_completeness = compare_rendered_inventory(
            delivery_ir,
            SEMANTIC_HTML_RE.findall(text),
            artifact_format="html",
        )
    except SemanticInventoryError as exc:
        raise VerificationError(str(exc)) from exc
    return {
        "format": "html",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "slide_count": slide_count,
        "offline": True,
        "javascript": False,
        "external_assets": False,
        "stylesheet_closure": {
            "status": "complete",
            "sha256": "sha256:" + HTML_STYLE_SHA256,
        },
        "visible_text_ledger": visible_text_ledger,
        "semantic_completeness": semantic_completeness,
    }
