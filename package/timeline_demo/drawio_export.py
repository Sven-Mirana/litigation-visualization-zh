"""GPL-3.0-only. Fixed, synthetic three-page r2 native draw.io adapter.

No generic exporter, viewer, renderer, network access, or XSD is included.
The caller verifies exact approved IR and PPTX bytes before this adapter runs.
"""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

sys.dont_write_bytecode = True
EMU_PER_PX = Decimal(9525)
NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}
PROFILES = (
    ("control", "Control · 旧版竖轨卡片"),
    ("a", "A · 横向比例时间带"),
    ("b", "B · 纵向卷宗登记簿"),
)
FILENAME = "timeline-r2-comparison.REVIEW-DRAFT.drawio"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def number(value: Decimal | int | str) -> str:
    result = format(Decimal(value).quantize(Decimal("0.000001")), "f").rstrip("0").rstrip(".")
    return result or "0"


def pixels(value: str | int) -> str:
    return number(Decimal(value) / EMU_PER_PX)


def color(element: ET.Element | None, fallback: str = "none") -> str:
    if element is None:
        return fallback
    rgb = element.find("a:srgbClr", NS)
    require(rgb is not None, "UNSUPPORTED_NON_RGB_COLOR")
    require(re.fullmatch(r"[0-9A-Fa-f]{6}", rgb.get("val", "")) is not None, "INVALID_RGB")
    return "#" + rgb.get("val", "").upper()


def shape_record(shape: ET.Element) -> dict:
    identity = shape.find("p:nvSpPr/p:cNvPr", NS)
    properties = shape.find("p:spPr", NS)
    require(identity is not None and properties is not None, "MISSING_SHAPE_IDENTITY")
    transform = properties.find("a:xfrm", NS)
    require(transform is not None and not transform.attrib, "UNSUPPORTED_TRANSFORM")
    offset, extent = transform.find("a:off", NS), transform.find("a:ext", NS)
    preset = properties.find("a:prstGeom", NS)
    require(preset is not None and preset.get("prst") in {"rect", "roundRect", "ellipse"}, "UNSUPPORTED_SHAPE")
    require(offset is not None and extent is not None, "MISSING_GEOMETRY")
    paragraphs = shape.findall("p:txBody/a:p", NS)
    text = "\n".join("".join(t.text or "" for t in p.findall(".//a:t", NS)) for p in paragraphs)
    runs = shape.findall("p:txBody/a:p/a:r", NS)
    require(not shape.findall(".//a:br", NS), "UNSUPPORTED_SOFT_LINE_BREAK")
    require(not text or len(paragraphs) == 1, "UNSUPPORTED_MULTIPARAGRAPH_LABEL")
    name = identity.get("name", "")
    semantic = re.search(r"\|SEMITEM\|([^|]+)\|", name)
    style = {
        "shape": "ellipse" if preset.get("prst") == "ellipse" else "rectangle",
        "rounded": "1" if preset.get("prst") == "roundRect" else "0",
        "arcSize": "16.666667",
        "fillColor": color(properties.find("a:solidFill", NS)),
        "strokeColor": color(properties.find("a:ln/a:solidFill", NS)),
        "strokeWidth": pixels(properties.find("a:ln", NS).get("w", "12700")) if properties.find("a:ln", NS) is not None else "0",
        "gradientColor": "none", "shadow": "0", "glass": "0",
        "html": "1", "overflow": "visible", "spacing": "0",
        "editable": "1", "movable": "1", "resizable": "1",
        "rotatable": "1", "deletable": "1", "connectable": "1",
        "autosize": "0",
    }
    if preset.get("prst") == "ellipse":
        style["perimeter"] = "ellipsePerimeter"
    if text:
        require(len(runs) == 1, "UNSUPPORTED_MIXED_TEXT_RUNS")
        rp = runs[0].find("a:rPr", NS)
        body = shape.find("p:txBody/a:bodyPr", NS)
        pp = paragraphs[0].find("a:pPr", NS)
        require(rp is not None and body is not None and pp is not None, "MISSING_TEXT_STYLE")
        style.update({
            "whiteSpace": "wrap" if body.get("wrap") == "square" else "nowrap",
            "fontSize": number(Decimal(rp.get("sz")) / 100 * Decimal(4) / 3),
            "fontFamily": rp.find("a:latin", NS).get("typeface"),
            "fontColor": color(rp.find("a:solidFill", NS)),
            "fontStyle": str(int(rp.get("b", "0")) + 2 * int(rp.get("i", "0"))),
            "align": {"l": "left", "ctr": "center", "r": "right"}[pp.get("algn", "l")],
            "verticalAlign": {"t": "top", "ctr": "middle", "b": "bottom"}[body.get("anchor", "t")],
            "spacingLeft": pixels(body.get("lIns", "91440")),
            "spacingRight": pixels(body.get("rIns", "91440")),
            "spacingTop": pixels(body.get("tIns", "45720")),
            "spacingBottom": pixels(body.get("bIns", "45720")),
            "lineHeight": number(Decimal(pp.find("a:lnSpc/a:spcPct", NS).get("val")) / 100000),
        })
    else:
        style.update({"whiteSpace": "nowrap", "fontSize": "12", "fontFamily": "Microsoft YaHei", "fontColor": "#152033", "fontStyle": "0", "align": "left", "verticalAlign": "middle"})
    return {
        "source_shape_id": identity.get("id"), "source_name": name,
        "source_id": name.split("|")[0], "semantic_id": semantic.group(1) if semantic else "",
        "label": text, "source_geometry": preset.get("prst"),
        "geometry": {"x": pixels(offset.get("x")), "y": pixels(offset.get("y")), "width": pixels(extent.get("cx")), "height": pixels(extent.get("cy"))},
        "style": style,
    }


def build(source: Path) -> tuple[bytes, dict]:
    ir_path = source / "internal-audit/delivery-ir.json"
    ir = json.loads(ir_path.read_text())
    require(ir["data_class"] == "synthetic" and ir["release_state"] == "REVIEW_DRAFT", "UNAUTHORIZED_SOURCE_CLASS")
    timeline = next(s for s in ir["slides"] if s["slide_id"] == "timeline-01")
    inventory = [i for i in ir["semantic_inventory"] if i["slide_id"] == "timeline-01"]
    mxfile = ET.Element("mxfile", {"host": "local-isolated-r2-export", "agent": "r2-native-pptx-to-drawio", "type": "device", "compressed": "false", "pages": "3"})
    pages = []
    for profile, page_name in PROFILES:
        pptx = source / f"timeline-profile-{profile}.REVIEW-DRAFT.pptx"
        pptx_raw = pptx.read_bytes()
        with zipfile.ZipFile(pptx) as archive:
            slide_raw = archive.read("ppt/slides/slide6.xml")
            slide = ET.fromstring(slide_raw)
            dimensions = ET.fromstring(archive.read("ppt/presentation.xml")).find("p:sldSz", NS)
        diagram = ET.SubElement(mxfile, "diagram", {"id": "r2-" + profile, "name": page_name})
        model = ET.SubElement(diagram, "mxGraphModel", {"dx": "0", "dy": "0", "grid": "0", "gridSize": "10", "guides": "1", "tooltips": "1", "connect": "1", "arrows": "1", "fold": "1", "page": "1", "pageScale": "1", "pageWidth": pixels(dimensions.get("cx")), "pageHeight": pixels(dimensions.get("cy")), "math": "0", "shadow": "0", "background": "#FFFFFF", "adaptiveColors": "none"})
        graph_root = ET.SubElement(model, "root")
        ET.SubElement(graph_root, "mxCell", {"id": "0"})
        ET.SubElement(graph_root, "mxCell", {"id": "1", "parent": "0"})
        shapes = slide.findall("p:cSld/p:spTree/p:sp", NS)
        require(len(shapes) == (15 if profile == "control" else 18), "SOURCE_SHAPE_COUNT_DRIFT")
        records = []
        for shape in shapes:
            record = shape_record(shape)
            attrs = {k: record[k] for k in ("source_shape_id", "source_name", "source_id", "semantic_id", "label")}
            attrs.update({"id": f"{profile}-s{record['source_shape_id']}", "source_slide": "6", "source_profile": profile, "source_pptx_sha256": digest(pptx_raw), "source_anchor_refs": " ".join(timeline["source_refs"]), "source_anchor_refs_scope": "slide", "release_state": "REVIEW_DRAFT", "data_class": "synthetic", "renderer_qa_inherited": "false"})
            wrapper = ET.SubElement(graph_root, "object", attrs)
            cell = ET.SubElement(wrapper, "mxCell", {"vertex": "1", "parent": "1", "style": ";".join(f"{k}={v}" for k, v in record["style"].items()) + ";"})
            ET.SubElement(cell, "mxGeometry", {**record["geometry"], "as": "geometry"})
            records.append(record)
        require([r["label"] for r in records if ":event-text:" in r["source_id"]] == [e["text"] for e in timeline["content"]["events"]], "EVENT_TEXT_DRIFT")
        require([r["label"] for r in records if ":event-date:" in r["source_id"]] == [e["date"] for e in timeline["content"]["events"]], "EVENT_DATE_DRIFT")
        require({r["semantic_id"] for r in records if r["semantic_id"]} == {i["semantic_id"] for i in inventory}, "SEMANTIC_ID_DRIFT")
        pages.append({"profile": profile, "page_name": page_name, "source_pptx": pptx.name, "source_pptx_sha256": digest(pptx_raw), "source_slide_part": "ppt/slides/slide6.xml", "source_slide_part_sha256": digest(slide_raw), "canvas_px": [pixels(dimensions.get("cx")), pixels(dimensions.get("cy"))], "source_refs": timeline["source_refs"], "objects": records})
    ET.indent(mxfile, space="  ")
    xml = ET.tostring(mxfile, encoding="utf-8", xml_declaration=True) + b"\n"
    ledger = {"schema": "r2-drawio-native-export-map/1.0", "scope": "timeline slide6 only, one page per source profile; not full decks", "release_state": "REVIEW_DRAFT", "data_class": "synthetic", "source_delivery_ir_sha256": digest(ir_path.read_bytes()), "geometry_rule": "all source x/y/width/height EMU divided by 9525; six decimals; no relayout", "source_line_representation": "thin rectangle vertices preserved as native thin rectangle vertices", "renderer_qa_inherited": False, "source_semantic_inventory": inventory, "page_count": 3, "native_object_count": sum(len(p["objects"]) for p in pages), "drawio_sha256": digest(xml), "pages": pages}
    return xml, ledger
