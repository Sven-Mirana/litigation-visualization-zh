# SPDX-License-Identifier: GPL-3.0-only
# Derived from the historical MIT release of this project.
# Copyright (c) 2026 李时瑀律师. Original MIT rights remain;
# modifications and combined file are GPL-3.0-only.
# See ../../../LICENSES/MIT.txt and root LICENSE-PROVENANCE.json.
#!/usr/bin/env python3
"""T4构建器（合同8644715d…）：同案独立冻结07为唯一语义输入→A01-A09锚（64位节hash+精确字符区间）
→case-views.json+view-spec.json。用法: build_t4.py --root . --t3-root <T3根> --vis-enabled
exit 0=OK / 3=HOLD-VIS"""
import sys, os, json, re, hashlib
from datetime import date
from pathlib import Path

CONTRACT_SHA = "8644715d0a145b06ae9387939d9f850d4b8ca1c252eb67076c30fe12665feae2"
MD = "07-诉讼案件办案方案工作底稿.md"
DOCX = "07-诉讼案件办案方案工作底稿.docx"
ANCHOR_TITLES = ["第一节　主体与角色","第二节　合同与交易链","第三节　履行与交付链","第四节　款项与余额",
                 "第五节　通知抗辩与期间","第六节　要件-事实-证据矩阵","第七节　证据索引",
                 "第八节　诉讼阶段计划","第九节　风险与暂停事项"]
VIEW_MAP = {"01-主体关系图": ["A01","A02"],
            "02-关键事件时间线": ["A02","A03","A04","A05"],
            "03-要件证据矩阵": ["A04","A06","A07"],
            "04-阶段计划与风险": ["A08","A09"]}
MAX_TIMELINE_EVENTS = 14
DATE_RE = re.compile(
    r"(?<!\d)(?:(\d{4})-(\d{1,2})-(\d{1,2})|(\d{4})年(\d{1,2})月(\d{1,2})日)(?!\d)"
)
DATE_LIKE_RE = re.compile(r"(?<!\d)\d{4}(?:-|年)\d{1,2}(?:-|月)\d{1,2}(?:日)?(?!\d)")
LIST_MARKER_RE = re.compile(r"^\s*(?:\d{1,3}[.、]\s*|[-*+]\s+)")
TIMELINE_CLASSIFICATION_ERROR = "TIMELINE_EVENT_CLASSIFICATION_UNREPRESENTABLE"
TIMELINE_LAYOUT_ERROR = "TIMELINE_LAYOUT_UNSAFE"
# This is deliberately a closed set.  A date by itself is context, not proof
# that an occurrence should be asserted on a timeline.
TIMELINE_OCCURRENCE_RE = re.compile(
    r"签订|签署|成立|生效|交付|验收|签收|送达|通知|催告|"
    r"付款|支付|收款|入账|欠付|逾期|解除|终止|起诉|立案|"
    r"受理|开庭|判决|裁定|调解|执行|提交|出具|完成|发生"
)
# These phrases state a cutoff, accounting basis or snapshot.  Even when an
# occurrence verb appears elsewhere in the same record, the line is not a
# mechanically safe event.
TIMELINE_EXCLUSION_RE = re.compile(
    r"截至|截止|基准(?:日|时点)?|对账|口径|统计时点|材料时点|"
    r"计算(?:至|到)|(?:日期|时间)(?:为|[:：])|期限|到期日"
)
TIMELINE_AMBIGUITY_RE = re.compile(
    r"大约|约于|约在|左右|前后|日期?不详|待核|尚待|疑似|可能|"
    r"据称|主张|争议|暂定|预计|拟于|计划于|将于|应于|应当于|"
    r"(?:日期|时间)[^，。；]{0,12}或"
)
TIMELINE_NEGATED_OCCURRENCE_RE = re.compile(
    r"(?:未|尚未|并未|没有)(?:予以|曾经|实际)?[^，。；]{0,8}"
    r"(?:签订|签署|成立|生效|交付|验收|签收|送达|通知|催告|"
    r"付款|支付|收款|入账|欠付|逾期|解除|终止|起诉|立案|"
    r"受理|开庭|判决|裁定|调解|执行|提交|出具|完成|发生)"
)

# S1's renderer consumes this exact plan.  Keeping wrap, coordinates and
# preflight in one module prevents a validator/renderer geometry split.
TIMELINE_SAFE_LEFT = 40.0
TIMELINE_SAFE_TOP = 108.0
TIMELINE_SAFE_RIGHT = 1560.0
TIMELINE_SAFE_BOTTOM = 860.0
TIMELINE_AXIS_Y = 330.0
TIMELINE_MILESTONE_Y = 620.0

def fsha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def hold(msg): print(f"HOLD-VIS: {msg}"); return 3

def strip_list_marker(line):
    """只移除锚定的列表标记，绝不把正文开头的年份或数值当作字符集剥除。"""
    return LIST_MARKER_RE.sub("", line.strip(), count=1)

def visual_width(ch):
    """Match the S1 renderer's deterministic CJK/ASCII width model."""
    return 1.0 if ord(ch) > 0x2E7F else 0.55

def wrap_visual(value, max_width):
    """Return the exact zero-truncation line split used by S1."""
    lines, current, width = [], "", 0.0
    for character in str(value):
        character_width = visual_width(character)
        if width + character_width > max_width and current:
            lines.append(current)
            current, width = character, character_width
        else:
            current += character
            width += character_width
    if current:
        lines.append(current)
    return lines or [""]

def _rendered_text_width(value, font_size):
    return sum(visual_width(character) for character in value) * font_size

def _boxes_overlap(first, second):
    return (
        min(first[2], second[2]) > max(first[0], second[0])
        and min(first[3], second[3]) > max(first[1], second[1])
    )

def timeline_layout_plan(events, milestones):
    """Build and validate the canonical 1600x900 S1 timeline layout.

    The returned lines and coordinates are rendered verbatim by
    ``mother-render_t4.py``.  Any unsafe text geometry therefore fails while
    the public runner is still in its input/build phase, before output staging
    exists.
    """
    event_plan = []
    text_blocks = []
    x0, x1 = 90.0, 1510.0
    count = len(events)
    for index, event in enumerate(events):
        x = x0 + (x1 - x0) * (index / max(count - 1, 1))
        label_x = min(max(x, 250.0), 1350.0)
        above = index % 2 == 0
        lines = wrap_visual(event["text"], 30)
        block_height = 18 + len(lines) * 17 + 14
        top = (
            TIMELINE_AXIS_Y - 40 - block_height
            if above
            else TIMELINE_AXIS_Y + 46
        )
        text_width = max(
            _rendered_text_width(event["date"], 14),
            *(_rendered_text_width(line, 13) for line in lines),
        )
        box = (
            label_x - text_width / 2,
            top,
            label_x + text_width / 2,
            top + block_height,
        )
        event_plan.append(
            {
                "x": x,
                "label_x": label_x,
                "above": above,
                "lines": lines,
                "block_height": block_height,
                "top": top,
                "box": box,
            }
        )
        text_blocks.append((f"event:{index + 1}", box))

    milestone_plan = []
    if milestones:
        heading = "未系日期事实（数据行全文）"
        heading_box = (
            90.0,
            TIMELINE_MILESTONE_Y - 28 - 16,
            90.0 + _rendered_text_width(heading, 16),
            TIMELINE_MILESTONE_Y - 28 + 4,
        )
        text_blocks.append(("milestone-heading", heading_box))
        baseline_y = TIMELINE_MILESTONE_Y
        for index, milestone in enumerate(milestones):
            lines = wrap_visual("◇ " + milestone["text"], 92)
            width = max(_rendered_text_width(line, 14) for line in lines)
            bottom = baseline_y + (len(lines) - 1) * 22 + 5
            box = (90.0, baseline_y - 14, 90.0 + width, bottom)
            milestone_plan.append(
                {"lines": lines, "baseline_y": baseline_y, "box": box}
            )
            text_blocks.append((f"milestone:{index + 1}", box))
            baseline_y += len(lines) * 22 + 8

    for label, box in text_blocks:
        if (
            box[0] < TIMELINE_SAFE_LEFT
            or box[1] < TIMELINE_SAFE_TOP
            or box[2] > TIMELINE_SAFE_RIGHT
            or box[3] > TIMELINE_SAFE_BOTTOM
        ):
            reason = (
                "MILESTONE_OUT_OF_BOUNDS"
                if label.startswith("milestone")
                else "TEXT_OUT_OF_SAFE_AREA"
            )
            raise ValueError(f"{TIMELINE_LAYOUT_ERROR}:{reason}:{label}")
    for left_index, (left_label, left_box) in enumerate(text_blocks):
        for right_label, right_box in text_blocks[left_index + 1:]:
            if _boxes_overlap(left_box, right_box):
                raise ValueError(
                    f"{TIMELINE_LAYOUT_ERROR}:TEXT_OVERLAP:{left_label}:{right_label}"
                )
    return {"events": event_plan, "milestones": milestone_plan}

def _validated_dates(line):
    for date_like in DATE_LIKE_RE.finditer(line):
        if DATE_RE.fullmatch(date_like.group(0)) is None:
            raise ValueError(f"非法日期格式:{date_like.group(0)}")
    parsed = []
    for matched in DATE_RE.finditer(line):
        raw = matched.group(0)
        groups = matched.groups()
        parts = groups[:3] if groups[0] is not None else groups[3:]
        try:
            normalized = date(*(int(part) for part in parts)).isoformat()
        except ValueError as exc:
            raise ValueError(f"非法日期:{raw}") from exc
        parsed.append(normalized)
    return parsed

def classify_timeline_line(line, anchor_id):
    """Classify one A02-A05 source occurrence without semantic inference."""
    if anchor_id not in {"A02", "A03", "A04", "A05"}:
        raise ValueError(f"{TIMELINE_CLASSIFICATION_ERROR}:ANCHOR:{anchor_id}")
    dates = _validated_dates(line)
    # A04 is structurally reserved for the amount/evidence projection.  Its
    # dates are accounting context and can never create a timeline event.
    if anchor_id == "A04":
        return {"kind": "other_projection"}
    if not dates:
        return {"kind": "undated"}
    if len(dates) != 1:
        raise ValueError(
            f"{TIMELINE_CLASSIFICATION_ERROR}:MULTIPLE_DATES:{anchor_id}"
        )
    if TIMELINE_AMBIGUITY_RE.search(line):
        raise ValueError(
            f"{TIMELINE_CLASSIFICATION_ERROR}:AMBIGUOUS_CONTEXT:{anchor_id}"
        )
    excluded = TIMELINE_EXCLUSION_RE.search(line) is not None
    negated = TIMELINE_NEGATED_OCCURRENCE_RE.search(line) is not None
    occurrence = TIMELINE_OCCURRENCE_RE.search(line) is not None and not negated
    if excluded or not occurrence:
        # A02 prose is already represented by the relationship-chain view.
        # A03/A05 have no other lawful DeliveryIR v1 projection, so silently
        # dropping or relabelling their dated context would break fidelity.
        if anchor_id == "A02":
            return {"kind": "other_projection"}
        reason = (
            "EXCLUDED_CONTEXT"
            if excluded
            else "NEGATED_OCCURRENCE"
            if negated
            else "NO_OCCURRENCE_VERB"
        )
        raise ValueError(
            f"{TIMELINE_CLASSIFICATION_ERROR}:{reason}:{anchor_id}"
        )
    return {"kind": "event", "date": dates[0]}

def extract_anchors(text):
    """返回A01-A09锚：exact char ranges + sha256(section utf8 bytes)。区间=节标题行首→下一节标题行首/文末。"""
    anchors = []
    idxs = []
    for i, title in enumerate(ANCHOR_TITLES):
        m = re.search(rf"^## {re.escape(title)}$", text, re.M)
        if not m: return None, f"缺节:{title}"
        idxs.append(m.start())
    if idxs != sorted(idxs): return None, "节序错乱"
    for i, title in enumerate(ANCHOR_TITLES):
        start = idxs[i]
        end = idxs[i+1] if i+1 < 9 else len(text)
        seg = text[start:end]
        anchors.append({"anchor_id": f"A{i+1:02d}", "title": title,
            "char_start": start, "char_end": end,
            "sha256": hashlib.sha256(seg.encode("utf-8")).hexdigest(),
            "hash_algorithm": "sha256-file-section-utf8/v1"})
    return anchors, None

def table_all(seg):
    rows = []
    for line in seg.splitlines():
        if line.startswith("|") and not re.match(r"^\|[\s\-|]+\|$", line):
            cells = [c.strip().replace("**","") for c in line.strip("|").split("|")]
            rows.append(cells)
    return rows
def table_rows(seg):
    rows = table_all(seg)
    return rows[1:] if rows else []  # 数据行（跳表头与分隔行）
def section_summary(seg):
    """表格节→数据行自然中文摘要（表头字段名=值）＋节内散文行全文；散文节→实质行。全文零截断。
    双口径表（表头含『口径』且≥2数据行）前置忠实摘要行（依节内纪律行）。"""
    rows = table_all(seg)
    outs = []
    if len(rows) >= 2:
        hdr = rows[0]
        if any("口径" in h for h in hdr) and len(rows) >= 3:
            outs.append("本节登记双口径余额，最终以对账核定为准（依本节纪律行）")
        for r in rows[1:]:
            outs.append("，".join(f"{hdr[j]}={r[j]}" if j < len(hdr) and hdr[j] else r[j]
                                   for j in range(len(r)) if r[j]))
    for l in seg.splitlines()[1:]:
        ls = l.strip()
        if ls and not ls.startswith("## ") and not ls.startswith("|"):
            outs.append(ls.replace("**",""))
            if rows and len(outs) > len(rows):  # 表格节只补散文行
                pass
            if not rows:
                break
    return outs

def _timeline_prose_items(seg, anchor_id):
    """Return only safely classified S1 timeline items from a prose anchor."""
    events, undated = [], []
    substantive_index = 0
    for line in seg.splitlines()[1:]:
        if not line.strip() or line.startswith("## "):
            continue
        if line.startswith("|"):
            raise ValueError(
                f"{TIMELINE_CLASSIFICATION_ERROR}:UNEXPECTED_TABLE:{anchor_id}"
            )
        text = strip_list_marker(line).replace("**", "")
        classification = classify_timeline_line(line, anchor_id)
        current_index = substantive_index
        substantive_index += 1
        if classification["kind"] == "event":
            events.append({"date": classification["date"], "text": text})
        elif classification["kind"] == "undated":
            undated.append({"text": text})
        elif classification["kind"] == "other_projection":
            # The S1 relationship view has a frozen six-item chain capacity.
            # A02 dated context beyond that capacity has no other rendered
            # projection, so it must not be silently discarded.
            if anchor_id == "A02" and current_index >= 6:
                raise ValueError(
                    f"{TIMELINE_CLASSIFICATION_ERROR}:"
                    "OTHER_PROJECTION_CAPACITY:A02"
                )
        else:
            raise ValueError(
                f"{TIMELINE_CLASSIFICATION_ERROR}:UNKNOWN_CLASS:{anchor_id}"
            )
    return events, undated

def build_case_views(text, case_id):
    anchors, err = extract_anchors(text)
    if err: return None, err
    seg = {a["anchor_id"]: text[a["char_start"]:a["char_end"]] for a in anchors}
    views = {}
    # 01 主体关系图：A01主体表 + A02交易链行
    parties = [{"text": " / ".join(c for c in r if c), "anchor_ids": ["A01"]} for r in table_rows(seg["A01"])][:8]
    chain = [{"text": strip_list_marker(l).replace("**",""), "anchor_ids": ["A02"]}
             for l in seg["A02"].splitlines()[1:] if l.strip() and not l.startswith("## ")][:6]
    views["01-主体关系图"] = {"anchor_ids": VIEW_MAP["01-主体关系图"], "parties": parties, "chain": chain}
    # 02 时间线：A02/A03/A05 only.  A04 is structurally reserved for the
    # amount/evidence projection and can never create an event or an undated
    # milestone, even when an amount row contains a date.
    events = []
    milestones = []
    try:
        for aid in ("A02", "A03", "A05"):
            anchor_events, anchor_undated = _timeline_prose_items(seg[aid], aid)
            events.extend({**event, "anchor_ids": [aid]} for event in anchor_events)
            milestones.extend(
                {**milestone, "anchor_ids": [aid]}
                for milestone in anchor_undated
            )
    except ValueError as exc:
        return None, str(exc)
    if len(events) > MAX_TIMELINE_EVENTS:
        return None, f"事件数{len(events)}超过上限{MAX_TIMELINE_EVENTS}"
    events.sort(key=lambda e: e["date"])
    try:
        timeline_layout_plan(events, milestones)
    except ValueError as exc:
        return None, str(exc)
    views["02-关键事件时间线"] = {"anchor_ids": VIEW_MAP["02-关键事件时间线"],
                                  "events": events, "undated_milestones": milestones}
    # 03 要件证据矩阵：A06矩阵表 + A04款项行 + A07索引
    matrix = [{"cells": r[:5], "anchor_ids": ["A06"]} for r in table_rows(seg["A06"])][:10]
    amounts = [{"cells": r[:4], "anchor_ids": ["A04"]} for r in table_rows(seg["A04"])][:6]
    evid = [{"text": l.strip().lstrip("·- "), "anchor_ids": ["A07"]}
            for l in seg["A07"].splitlines()[1:] if l.strip() and not l.startswith("## ")][:4]
    views["03-要件证据矩阵"] = {"anchor_ids": VIEW_MAP["03-要件证据矩阵"],
                              "matrix": matrix, "amounts": amounts, "evidence_index": evid}
    # 04 阶段计划与风险：A08阶段表 + A09风险表（暂停/待核与法条未注入必须可见）
    stages = [{"cells": r[:3], "anchor_ids": ["A08"]} for r in table_rows(seg["A08"])][:8]
    risks = [{"cells": r[:4], "anchor_ids": ["A09"]} for r in table_rows(seg["A09"])][:12]
    if not any("法条" in "".join(r["cells"]) or "法源" in "".join(r["cells"]) for r in risks):
        risks.append({"cells": ["提示","待人工法律复核","全部法条引用未注入","人工终签"], "anchor_ids": ["A09"]})
    views["04-阶段计划与风险"] = {"anchor_ids": VIEW_MAP["04-阶段计划与风险"], "stages": stages, "risks": risks}
    return {"schema": "gaotao.t4.case-view-data.v1", "case_id": case_id,
            "anchors": anchors, "views": views,
            "boundary_note": "全部数据仅取自同案冻结07；待核/暂停口径原样保留；无新增事实或法律结论"}, None

def main():
    a = sys.argv[1:]
    def arg(n): return a[a.index(n)+1] if n in a else None
    root = Path(arg("--root") or ".").resolve()
    t3root = Path(arg("--t3-root") or "").resolve()
    if "--vis-enabled" not in a:
        return hold("VIS未启用（--vis-enabled缺失），拒绝生成任何视图")
    cp = root/"contract/T4-VIS-ACCEPTANCE-CONTRACT.json"
    if not cp.is_file() or fsha(cp) != CONTRACT_SHA: return hold("T4合同副本缺失或哈希失配")
    contract = json.loads(cp.read_text(encoding="utf-8"))
    # 前置：T3联合PASS须先于任何T4写入
    t3ar_p = t3root/"T3-AS-RUN.json"
    if not t3ar_p.is_file(): return hold("T3 AS-RUN缺失")
    t3ar = json.loads(t3ar_p.read_text(encoding="utf-8"))
    if t3ar.get("result") != "PASS" or t3ar.get("stage") != "T3":
        return hold("T3文本门未通过（result≠PASS）")
    if t3ar.get("text_gate_message_id") != contract["prerequisite"]["text_gate_message_id"]:
        return hold("T3文本门消息id不符")
    prepared = []
    # Validate every case, including the canonical timeline layout, before the
    # first output directory or artifact is created.
    for c in contract["cases"]:
        fmd = t3root/c["frozen_content_dir"]/MD
        fdx = t3root/c["frozen_content_dir"]/DOCX
        if not fmd.is_file(): return hold(f"冻结07缺失:{c['run_id']}")
        if fmd.is_symlink() or fdx.is_symlink(): return hold("冻结07为symlink")
        if fsha(fmd) != c["frozen_md_sha256"]:
            return hold(f"冻结07与合同哈希不符（篡改或跨案输入）:{c['run_id']}")
        if fdx.is_file() and fsha(fdx) != c["frozen_docx_sha256"]:
            return hold(f"冻结DOCX与合同哈希不符:{c['run_id']}")
        text = fmd.read_text(encoding="utf-8")
        cv, err = build_case_views(text, c["case_id"])
        if err: return hold(f"{c['run_id']}锚提取失败:{err}")
        cv["input"] = {"frozen_md": str(fmd), "frozen_md_sha256": c["frozen_md_sha256"], "run_id": c["run_id"]}
        prepared.append((c, cv))
    for c, cv in prepared:
        outd = root/c["output_dir"]; outd.mkdir(parents=True, exist_ok=True)
        (outd/"case-views.json").write_text(json.dumps(cv, ensure_ascii=False, indent=1)+"\n", encoding="utf-8")
        spec = {"schema": "gaotao.t4.case-view-spec.v1", "case_id": c["case_id"], "run_id": c["run_id"],
                "views": [{"name": v, "svg": f"{v}.svg", "png": f"{v}.png",
                           "width": 1600, "height": 900, "anchor_ids": VIEW_MAP[v]} for v in VIEW_MAP]}
        (outd/"view-spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1)+"\n", encoding="utf-8")
        print(f"BUILD[{c['run_id']}]: 9锚+4视图数据")
    return 0
if __name__ == "__main__": sys.exit(main())
