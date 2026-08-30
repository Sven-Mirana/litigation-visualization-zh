from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


CANDIDATE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CANDIDATE / "package"))
MODULE_PATH = CANDIDATE / "package" / "client_delivery" / "html_writer.py"
QA_PATH = CANDIDATE / "package" / "client_delivery" / "html_qa.py"
PLAYWRIGHT_CHROME_AVAILABLE = (
    importlib.util.find_spec("playwright") is not None
    and any(
        path.is_file()
        for path in (
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        )
    )
)
SPEC = importlib.util.spec_from_file_location("s2_html_writer", MODULE_PATH)
assert SPEC and SPEC.loader
html_writer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(html_writer)

from client_delivery.semantic_inventory import build_source_inventory
from client_delivery.verify import VerificationError, verify_html


def sample_ir(confidentiality: str = "INTERNAL_REVIEW_ONLY") -> dict:
    ir = {
        "schema": "client-delivery-ir/v1",
        "source_schema": {
            "schema": "frozen07-source-schema/1.0",
            "variant": "canonical-v1",
            "table_headers": {
                "A01": ["主体", "角色", "要点", "来源"],
                "A04": ["项目", "金额（元）", "口径"],
                "A06": ["要件", "事实", "证据", "缺口", "状态"],
                "A08": ["阶段", "动作", "出口"],
                "A09": ["编号", "类别", "内容", "解除条件"],
            },
        },
        "case_ref": "SYNTHETIC-001",
        "data_class": "synthetic",
        "release_state": "review_draft",
        "input_sha256": "0" * 64,
        "profile_sha256": "1" * 64,
        "profile": {
            "title": "诉讼案件可视化报告",
            "subtitle": "客户沟通材料",
            "client_label": "某客户 & 合伙人",
            "matter_label": "示例合同争议",
            "version": "v1.0",
            "materials_as_of": "2026-08-14",
            "prepared_by": "诉讼团队",
            "confidentiality": confidentiality,
        },
        "sources": [
            {"source_id": "SRC-01", "label": "已冻结材料一"},
            {"source_id": "SRC-02", "label": "已冻结材料二"},
        ],
        "slides": [
            {
                "slide_id": "S01",
                "role": "cover",
                "title": "示例合同争议",
                "source_refs": [],
                "content": {"profile": {}},
            },
            {
                "slide_id": "S02",
                "role": "executive_summary",
                "title": "执行摘要",
                "source_refs": ["SRC-01"],
                "content": {"items": [{"text": "争议焦点仍待律师确认"}]},
            },
            {
                "slide_id": "S03",
                "role": "relationship",
                "title": "主体关系",
                "source_refs": ["SRC-01"],
                "content": {
                    "parties": [{"text": "甲方"}, {"text": "乙方"}],
                    "chain": [{"text": "甲方与乙方签订合同"}],
                },
            },
            {
                "slide_id": "S04",
                "role": "timeline",
                "title": "关键时间线",
                "source_refs": ["SRC-01"],
                "content": {
                    "events": [{"date": "2026-01-01", "text": "签订合同"}],
                    "undated_milestones": [{"text": "补充核对送达日期"}],
                },
            },
            {
                "slide_id": "S05",
                "role": "evidence_matrix",
                "title": "要件与证据",
                "source_refs": ["SRC-01", "SRC-02"],
                "content": {
                    "rows": [
                        {"cells": ["要件", "现有证据", "状态"]},
                        {"cells": ["合同成立", "合同文本", "待复核"]},
                    ],
                    "amounts": [
                        {"cells": ["项目", "金额"]},
                        {"cells": ["本金", "100.00"]},
                    ],
                    "amount_notes": [],
                    "evidence_index": [{"text": "E-01 合同文本"}],
                },
            },
            {
                "slide_id": "S06",
                "role": "stage_risk",
                "title": "阶段与风险",
                "source_refs": ["SRC-02"],
                "content": {
                    "stages": [
                        {"cells": ["阶段", "动作"]},
                        {"cells": ["审前", "补充证据"]},
                    ],
                    "risks": [
                        {"cells": ["风险", "应对"]},
                        {"cells": ["时效", "人工核验"]},
                    ],
                },
            },
            {
                "slide_id": "S07",
                "role": "next_steps",
                "title": "缺口与下一步",
                "source_refs": ["SRC-02"],
                "content": {
                    "items": [{"text": "核对合同原件"}],
                    "gaps": [{"text": "缺少送达凭证"}],
                },
            },
            {
                "slide_id": "S08",
                "role": "scope",
                "title": "范围与说明",
                "source_refs": ["SRC-01", "SRC-02"],
                "content": {
                    "items": [{"text": "仅基于当前冻结材料"}],
                    "materials_as_of": "2026-08-14",
                    "boundary": "零格式返工不替代律师复核。",
                },
            },
        ],
    }
    ir["slides"][0]["content"]["profile"] = {
        key: ir["profile"][key]
        for key in (
            "client_label",
            "matter_label",
            "materials_as_of",
            "prepared_by",
            "confidentiality",
        )
    }
    ir["semantic_inventory"] = build_source_inventory(ir["slides"])
    return ir


class S2HtmlWriterTests(unittest.TestCase):
    def render(self, ir: dict, root: Path, name: str = "client-report.html"):
        output = root / name
        receipt = html_writer.render_html(ir, output)
        return output, receipt, output.read_text(encoding="utf-8")

    def test_single_file_offline_deterministic_and_receipted(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output_a, receipt_a, text_a = self.render(sample_ir(), root, "a.html")
            output_b, receipt_b, text_b = self.render(sample_ir(), root, "b.html")

            self.assertEqual(output_a.read_bytes(), output_b.read_bytes())
            self.assertEqual(receipt_a, receipt_b)
            self.assertEqual(8, receipt_a["slide_count"])
            self.assertEqual(len(output_a.read_bytes()), receipt_a["size"])
            self.assertEqual(
                hashlib.sha256(output_a.read_bytes()).hexdigest(), receipt_a["sha256"]
            )
            self.assertEqual({"a.html", "b.html"}, {path.name for path in root.iterdir()})
            self.assertIn("审阅稿", text_a)
            self.assertIn("仅供内部审阅", text_a)
            self.assertIn("诉讼可视化", text_a)
            self.assertNotIn("REVIEW DRAFT", text_a)
            self.assertNotIn("INTERNAL_REVIEW_ONLY", text_a)
            self.assertNotIn("Arial", text_a)
            self.assertEqual(8, text_a.count('<article class="slide role-'))
            self.assertIn("某客户 &amp; 合伙人", text_a)
            self.assertIn("示例合同争议", text_a)
            self.assertIn("零格式返工不替代律师复核。", text_a)
            self.assertIn('关系链条</h3><ul class="item-list">', text_a)
            self.assertNotIn('关系链条</h3><ol class="item-list">', text_a)

    def test_fixed_customer_chrome_uses_closed_simplified_chinese_mappings(self):
        expected = {
            "CONFIDENTIAL": "机密",
            "ATTORNEY_WORK_PRODUCT": "律师工作成果",
            "INTERNAL_REVIEW_ONLY": "仅供内部审阅",
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for index, (machine_value, display_value) in enumerate(expected.items()):
                with self.subTest(machine_value=machine_value):
                    ir = sample_ir(machine_value)
                    output, _, text = self.render(ir, root, f"mapped-{index}.html")
                    self.assertIn(display_value, text)
                    self.assertNotIn(machine_value, text)
                    self.assertIn("审阅稿", text)
                    self.assertNotIn("REVIEW DRAFT", text)
                    self.assertEqual("complete", verify_html(output, ir)["visible_text_ledger"]["status"])

            forged_ir = sample_ir()
            with mock.patch.object(html_writer, "_DISPLAY_REVIEW_STATE", "REVIEW DRAFT"):
                forged, _, _ = self.render(forged_ir, root, "forged-state.html")
            with self.assertRaisesRegex(VerificationError, "legacy English|Simplified Chinese"):
                verify_html(forged, forged_ir)

            with mock.patch.dict(
                html_writer._DISPLAY_CONFIDENTIALITY,
                {"INTERNAL_REVIEW_ONLY": "INTERNAL_REVIEW_ONLY"},
                clear=False,
            ):
                forged_confidentiality, _, _ = self.render(
                    forged_ir, root, "forged-confidentiality.html"
                )
            with self.assertRaisesRegex(VerificationError, "confidentiality display mapping"):
                verify_html(forged_confidentiality, forged_ir)

    def test_release_mark_is_anchored_per_article_not_a_global_substring(self):
        """A document-wide 审阅稿 substring must not satisfy the release mark:
        source text can supply it, so every article needs its own watermark."""
        ir = sample_ir()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output, _, text = self.render(ir, root, "anchored.html")
            self.assertEqual(
                "complete", verify_html(output, ir)["visible_text_ledger"]["status"]
            )
            watermark_count = text.count('data-static-id="watermark:release-state"')
            self.assertEqual(len(ir["slides"]), watermark_count)

            watermark_pattern = re.compile(
                r'<div class="watermark" data-static-id="watermark:release-state"'
                r' data-visible-text-sha256="sha256:[0-9a-f]{64}">审阅稿</div>'
            )
            article_pattern = re.compile(
                r'<article class="slide role-[^"]*"'
                r' data-visible-owner-count="(\d+)"'
                r' data-visible-owner-ledger-sha256="sha256:[0-9a-f]{64}">(.*?)</article>',
                re.DOTALL,
            )
            articles = article_pattern.findall(text)
            self.assertEqual(len(ir["slides"]), len(articles))

            def rebuild(match: re.Match) -> str:
                inner = watermark_pattern.sub("", match.group(2), count=1)
                owners = [list(item) for item in html_writer._OWNER_ATTR_RE.findall(inner)]
                payload = json.dumps(
                    owners, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
                digest = hashlib.sha256(payload).hexdigest()
                head = match.group(0).split(">", 1)[0]
                head = re.sub(r'data-visible-owner-count="\d+"',
                              f'data-visible-owner-count="{len(owners)}"', head)
                head = re.sub(r'data-visible-owner-ledger-sha256="sha256:[0-9a-f]{64}"',
                              f'data-visible-owner-ledger-sha256="sha256:{digest}"', head)
                return f"{head}>{inner}</article>"

            # Remove one article's watermark AND regenerate that article's
            # self-declared ledger, so the pre-existing owner-ledger and
            # unregistered-text gates are satisfied and only the new
            # per-article anchoring rule can reject the document.
            stripped = article_pattern.sub(rebuild, text, count=1)
            self.assertEqual(watermark_count - 1,
                             stripped.count('data-static-id="watermark:release-state"'))
            self.assertIn("审阅稿", stripped)
            broken = root / "no-watermark.html"
            broken.write_text(stripped, encoding="utf-8")
            with self.assertRaisesRegex(
                VerificationError, "release-state watermark owner"
            ):
                verify_html(broken, ir)

    def test_r3_static_role_text_location_order_and_presence_are_exact(self):
        """Recomputed self-receipts cannot authorize static-chrome drift."""

        ir = sample_ir()
        article_pattern = re.compile(
            r'(<article class="slide role-[^"]*"[^>]*>)(.*?)(</article>)',
            re.DOTALL,
        )

        def rebuild_receipts(text: str) -> str:
            def rebuild(match: re.Match) -> str:
                head, inner, tail = match.groups()
                owners = [list(item) for item in html_writer._OWNER_ATTR_RE.findall(inner)]
                payload = json.dumps(
                    owners, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
                digest = hashlib.sha256(payload).hexdigest()
                head = re.sub(
                    r'data-visible-owner-count="\d+"',
                    f'data-visible-owner-count="{len(owners)}"',
                    head,
                )
                head = re.sub(
                    r'data-visible-owner-ledger-sha256="sha256:[0-9a-f]{64}"',
                    f'data-visible-owner-ledger-sha256="sha256:{digest}"',
                    head,
                )
                return f"{head}{inner}{tail}"

            return article_pattern.sub(rebuild, text)

        def replace_static_text(text: str) -> str:
            replacement = "任意未登记中文标签"
            digest = hashlib.sha256(replacement.encode("utf-8")).hexdigest()
            changed, count = re.subn(
                r'(<p class="lead" data-static-id="cover-lead" '
                r'data-visible-text-sha256=")sha256:[0-9a-f]{64}("[^>]*>).*?(</p>)',
                rf'\1sha256:{digest}\2{replacement}\3',
                text,
                count=1,
            )
            self.assertEqual(1, count)
            return rebuild_receipts(changed)

        def replace_static_location(text: str) -> str:
            changed, count = re.subn(
                r'data-static-id="cover-lead"',
                'data-static-id="scope:boundary"',
                text,
                count=1,
            )
            self.assertEqual(1, count)
            return rebuild_receipts(changed)

        def reorder_static_owners(text: str) -> str:
            articles = list(article_pattern.finditer(text))
            self.assertGreaterEqual(len(articles), 2)
            match = articles[1]
            head, inner, tail = match.groups()
            watermark = re.search(
                r'<div class="watermark"[^>]*data-static-id="watermark:release-state"[^>]*>.*?</div>',
                inner,
                re.DOTALL,
            )
            role_label = re.search(
                r'<p class="eyebrow"[^>]*data-static-id="header:role-label"[^>]*>.*?</p>',
                inner,
                re.DOTALL,
            )
            self.assertIsNotNone(watermark)
            self.assertIsNotNone(role_label)
            swapped = inner.replace(watermark.group(0), "__R3_WATERMARK__", 1)
            swapped = swapped.replace(role_label.group(0), watermark.group(0), 1)
            swapped = swapped.replace("__R3_WATERMARK__", role_label.group(0), 1)
            changed = text[: match.start()] + head + swapped + tail + text[match.end() :]
            return rebuild_receipts(changed)

        def remove_static_owner(text: str) -> str:
            changed, count = re.subn(
                r'<p class="lead"[^>]*data-static-id="cover-lead"[^>]*>.*?</p>',
                "",
                text,
                count=1,
                flags=re.DOTALL,
            )
            self.assertEqual(1, count)
            return rebuild_receipts(changed)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output, _, text = self.render(ir, root, "static-ledger.html")
            self.assertEqual(
                "complete", verify_html(output, ir)["visible_text_ledger"]["status"]
            )
            for label, mutation in (
                ("text", replace_static_text),
                ("location", replace_static_location),
                ("order", reorder_static_owners),
                ("missing", remove_static_owner),
            ):
                with self.subTest(label=label):
                    output.write_text(mutation(text), encoding="utf-8")
                    with self.assertRaisesRegex(
                        VerificationError, "HTML_STATIC_LEDGER_INVALID"
                    ):
                        verify_html(output, ir)
            closure_mutations = (
                (
                    "css-generated-content",
                    text.replace(
                        "</style>",
                        '.slide::after { content: "任意未登记中文标签"; '
                        "position: absolute; left: 100px; top: 100px; }</style>",
                        1,
                    ),
                    "HTML_STYLESHEET_INVALID",
                ),
                (
                    "duplicate-role-class",
                    text.replace(
                        'class="slide role-cover"',
                        'class="slide role-cover role-scope"',
                        1,
                    ),
                    "HTML_STATIC_LEDGER_INVALID",
                ),
                (
                    "outside-article-visible-text",
                    text.replace(
                        '<body><div class="deck">',
                        '<body><p>任意未登记中文标签</p><div class="deck">',
                        1,
                    ),
                    "SILENT_TRUNCATION_DETECTED",
                ),
            )
            for label, mutated, error in closure_mutations:
                with self.subTest(label=label):
                    output.write_text(mutated, encoding="utf-8")
                    with self.assertRaisesRegex(VerificationError, error):
                        verify_html(output, ir)

    def test_legacy_english_marker_scan_is_case_and_separator_insensitive(self):
        from client_delivery.verify import _contains_legacy_english_chrome

        for value in (
            "REVIEW DRAFT",
            "Review Draft",
            "review draft",
            "REVIEW-DRAFT",
            "REVIEW_DRAFT",
            "ReviewDraft",
            "CLIENT_READY",
            "Client Ready",
            "CONFIDENTIAL",
            "Litigation Brief",
            "client delivery",
            "internal_review_only",
        ):
            with self.subTest(value=value):
                self.assertTrue(_contains_legacy_english_chrome(value))
        for value in ("审阅稿", "机密", "诉讼可视化", "仅供内部审阅", "A01", ""):
            with self.subTest(value=value):
                self.assertFalse(_contains_legacy_english_chrome(value))

    @unittest.skipUnless(
        PLAYWRIGHT_CHROME_AVAILABLE, "system Python Playwright/Chrome not configured"
    )
    def test_python_playwright_doctor_and_screen_print_qa_need_no_node_runtime(self):
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"RUNTIME_NODE", "RUNTIME_NODE_MODULES", "RUNTIME_BIN_DIR"}
        }
        doctor = subprocess.run(
            [sys.executable, str(QA_PATH), "--doctor"],
            capture_output=True,
            text=True,
            env={**env, "PYTHONDONTWRITEBYTECODE": "1"},
            timeout=30,
        )
        self.assertEqual(0, doctor.returncode, doctor.stderr)
        doctor_report = json.loads(doctor.stdout.strip().splitlines()[-1])
        self.assertEqual("python-playwright-chromium", doctor_report["engine"])
        self.assertEqual("1.59.0", doctor_report["playwright_version"])
        self.assertFalse(doctor_report["codex_runtime_required"])
        self.assertFalse(doctor_report["node_runtime_required"])

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ir = sample_ir()
            output, _, _ = self.render(ir, root)
            result = subprocess.run(
                [
                    sys.executable,
                    str(QA_PATH),
                    "--input",
                    str(output),
                    "--expected-slides",
                    "8",
                    "--delivery-ir-stdin",
                ],
                capture_output=True,
                text=True,
                input=json.dumps(ir, ensure_ascii=False, separators=(",", ":")),
                env={**env, "PYTHONDONTWRITEBYTECODE": "1"},
                timeout=120,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            receipt = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertEqual("python-playwright-chromium", receipt["engine"])
            self.assertEqual(0, receipt["networkRequests"])
            self.assertEqual(8, receipt["printPageCount"])
            self.assertEqual(0, receipt["screen"]["articleOverflowPx"])
            self.assertEqual(0, receipt["print"]["articleOverflowPx"])
            self.assertEqual(0, receipt["screen"]["articleHorizontalOverflowPx"])
            self.assertEqual(0, receipt["print"]["articleHorizontalOverflowPx"])
            self.assertEqual(0, receipt["screen"]["articleVerticalOverflowPx"])
            self.assertEqual(0, receipt["print"]["articleVerticalOverflowPx"])
            self.assertEqual("complete", receipt["screen"]["visibleTextClosureStatus"])
            self.assertEqual("complete", receipt["print"]["visibleTextClosureStatus"])
            self.assertEqual(0, receipt["screen"]["unregisteredVisibleTextCount"])
            self.assertEqual(0, receipt["print"]["unregisteredVisibleTextCount"])
            self.assertEqual(0, receipt["screen"]["ownerHashFailureCount"])
            self.assertEqual(0, receipt["print"]["ownerHashFailureCount"])
            self.assertEqual("complete", receipt["screen"]["staticRoleLedgerStatus"])
            self.assertEqual("complete", receipt["print"]["staticRoleLedgerStatus"])
            self.assertEqual("complete", receipt["screen"]["releaseWatermarkStatus"])
            self.assertEqual("complete", receipt["print"]["releaseWatermarkStatus"])
            self.assertEqual("complete", receipt["screen"]["nowrapStatus"])
            self.assertEqual("complete", receipt["print"]["nowrapStatus"])

        unavailable = subprocess.run(
            [sys.executable, str(QA_PATH), "--doctor"],
            capture_output=True,
            text=True,
            env={**env, "S2_HTML_QA_FORCE_UNAVAILABLE": "1"},
            timeout=20,
        )
        self.assertEqual(3, unavailable.returncode)
        self.assertIn("Playwright/Chrome", unavailable.stderr)

    @unittest.skipUnless(
        PLAYWRIGHT_CHROME_AVAILABLE, "system Python Playwright/Chrome not configured"
    )
    def test_browser_qa_rejects_nonsemantic_horizontal_article_overflow(self):
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"RUNTIME_NODE", "RUNTIME_NODE_MODULES", "RUNTIME_BIN_DIR"}
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ir = sample_ir()
            output, _, text = self.render(ir, root)
            mutated, count = re.subn(
                r"(<article\b[^>]*>)",
                (
                    r'\1<div style="position:absolute;left:1400px;top:40px;'
                    r'width:20px;height:20px">UNREGISTERED-CUSTOMER-TEXT</div>'
                ),
                text,
                count=1,
            )
            self.assertEqual(1, count)
            output.write_text(mutated, encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(QA_PATH),
                    "--input",
                    str(output),
                    "--expected-slides",
                    "8",
                    "--delivery-ir-stdin",
                ],
                capture_output=True,
                text=True,
                input=json.dumps(ir, ensure_ascii=False, separators=(",", ":")),
                env={**env, "PYTHONDONTWRITEBYTECODE": "1"},
                timeout=120,
            )
            self.assertEqual(1, result.returncode, result.stderr)
            self.assertIn("visible text closure", result.stderr)
            self.assertIn("articleHorizontalOverflowPx", result.stderr)
            self.assertIn('"unregisteredVisibleTextCount": 1', result.stderr)

    @unittest.skipUnless(
        PLAYWRIGHT_CHROME_AVAILABLE, "system Python Playwright/Chrome not configured"
    )
    def test_browser_qa_rejects_unregistered_visible_text_and_semantic_inner_injection(self):
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"RUNTIME_NODE", "RUNTIME_NODE_MODULES", "RUNTIME_BIN_DIR"}
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ir = sample_ir()
            output, _, text = self.render(ir, root)
            first_semantic = re.search(
                r'(<[^>]+\bdata-semantic-id="[^"]+"[^>]*>)', text
            )
            self.assertIsNotNone(first_semantic)

            article_pattern = re.compile(
                r'(<article class="slide role-[^"]*"[^>]*>)(.*?)(</article>)',
                re.DOTALL,
            )

            def rebuild_receipts(value: str) -> str:
                def rebuild(match: re.Match) -> str:
                    head, inner, tail = match.groups()
                    owners = [
                        list(item) for item in html_writer._OWNER_ATTR_RE.findall(inner)
                    ]
                    payload = json.dumps(
                        owners, ensure_ascii=False, separators=(",", ":")
                    ).encode("utf-8")
                    digest = hashlib.sha256(payload).hexdigest()
                    head = re.sub(
                        r'data-visible-owner-count="\d+"',
                        f'data-visible-owner-count="{len(owners)}"',
                        head,
                    )
                    head = re.sub(
                        r'data-visible-owner-ledger-sha256="sha256:[0-9a-f]{64}"',
                        f'data-visible-owner-ledger-sha256="sha256:{digest}"',
                        head,
                    )
                    return f"{head}{inner}{tail}"

                return article_pattern.sub(rebuild, value)

            replacement = "任意未登记中文标签"
            replacement_digest = hashlib.sha256(
                replacement.encode("utf-8")
            ).hexdigest()
            static_text_drift, static_text_count = re.subn(
                r'(<p class="lead" data-static-id="cover-lead" '
                r'data-visible-text-sha256=")sha256:[0-9a-f]{64}("[^>]*>).*?(</p>)',
                rf'\1sha256:{replacement_digest}\2{replacement}\3',
                text,
                count=1,
            )
            self.assertEqual(1, static_text_count)
            static_text_drift = rebuild_receipts(static_text_drift)

            watermark_removed, watermark_removed_count = re.subn(
                r'<div class="watermark"[^>]*data-static-id="watermark:release-state"[^>]*>.*?</div>',
                "",
                text,
                count=1,
                flags=re.DOTALL,
            )
            self.assertEqual(1, watermark_removed_count)
            watermark_removed = rebuild_receipts(watermark_removed)

            static_location_drift, static_location_count = re.subn(
                r'data-static-id="cover-lead"',
                'data-static-id="scope:boundary"',
                text,
                count=1,
            )
            self.assertEqual(1, static_location_count)
            static_location_drift = rebuild_receipts(static_location_drift)

            mutations = {
                "unregistered-page-visible": re.sub(
                    r"(<article\b[^>]*>)",
                    (
                        r'\1<p style="position:absolute;left:120px;top:120px;'
                        r'width:360px;height:30px">UNREGISTERED-PAGE-VISIBLE</p>'
                    ),
                    text,
                    count=1,
                ),
                "semantic-inner-injection": text.replace(
                    first_semantic.group(1),
                    first_semantic.group(1) + "<span>SEMANTIC-INNER-SENTINEL</span>",
                    1,
                ),
                "css-generated-content": text.replace(
                    "</style>",
                    '.slide::after { content: "任意未登记中文标签"; '
                    "position: absolute; left: 100px; top: 100px; }</style>",
                    1,
                ),
                "outside-article-visible-text": text.replace(
                    '<body><div class="deck">',
                    '<body><p>任意未登记中文标签</p><div class="deck">',
                    1,
                ),
                "watermark-wrap-enabled": text.replace(
                    "white-space: nowrap;", "white-space: normal;", 1
                ),
                "cover-meta-label-wrap-enabled": text.replace(
                    ".meta-row dt { color: var(--muted); white-space: nowrap; }",
                    ".meta-row dt { color: var(--muted); white-space: normal; }",
                    1,
                ),
                "header-role-wrap-enabled": text.replace(
                    ".slide-header > .eyebrow { white-space: nowrap; }",
                    ".slide-header > .eyebrow { white-space: normal; }",
                    1,
                ),
                "footer-document-wrap-enabled": text.replace(
                    '.slide-footer > [data-static-id="footer:document-label"] { white-space: nowrap; }',
                    '.slide-footer > [data-static-id="footer:document-label"] { white-space: normal; }',
                    1,
                ),
                "header-role-print-wrap-enabled": text.replace(
                    "</style>",
                    '@media print { .slide-header > .eyebrow { white-space: normal; } }</style>',
                    1,
                ),
                "footer-document-print-wrap-enabled": text.replace(
                    "</style>",
                    '@media print { .slide-footer > [data-static-id="footer:document-label"] { white-space: normal; } }</style>',
                    1,
                ),
                "static-text-self-consistent": static_text_drift,
                "static-location-self-consistent": static_location_drift,
                "watermark-missing-self-consistent": watermark_removed,
                # Owner-attributed but unhashed: excluded from every hash/ID
                # gate while the unregistered-text walker still treats its text
                # as owned.  The browser side must reject it on its own.
                "unhashed-owner-english-chrome": re.sub(
                    r"(<article\b[^>]*>)",
                    (
                        r'\1<div data-static-id="watermark:release-state"'
                        r' style="position:absolute;left:140px;top:160px;'
                        r'width:260px;height:30px">REVIEW DRAFT</div>'
                    ),
                    text,
                    count=1,
                ),
            }
            for label, mutated in mutations.items():
                with self.subTest(label=label):
                    output.write_text(mutated, encoding="utf-8")
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(QA_PATH),
                            "--input",
                            str(output),
                            "--expected-slides",
                            "8",
                            "--delivery-ir-stdin",
                        ],
                        capture_output=True,
                        text=True,
                        input=json.dumps(
                            ir, ensure_ascii=False, separators=(",", ":")
                        ),
                        env={**env, "PYTHONDONTWRITEBYTECODE": "1"},
                        timeout=120,
                    )
                    self.assertEqual(1, result.returncode, result.stderr)
                    self.assertIn("visible text closure", result.stderr)
                    if label == "watermark-wrap-enabled":
                        self.assertIn('"nowrapFailureCount": 1', result.stderr)
                    elif label == "cover-meta-label-wrap-enabled":
                        self.assertIn('"nowrapFailureCount": 4', result.stderr)
                    elif label in {
                        "header-role-wrap-enabled",
                        "header-role-print-wrap-enabled",
                    }:
                        self.assertIn('"nowrapFailureCount": 1', result.stderr)
                    elif label in {
                        "footer-document-wrap-enabled",
                        "footer-document-print-wrap-enabled",
                    }:
                        self.assertIn('"nowrapFailureCount": 1', result.stderr)
                    elif label in {
                        "static-text-self-consistent",
                        "static-location-self-consistent",
                    }:
                        self.assertIn('"staticLedgerMatches": false', result.stderr)
                        self.assertIn('"visibleOwnerLedgerMatches": true', result.stderr)
                        self.assertIn('"ownerHashFailureCount": 0', result.stderr)
                    elif label == "watermark-missing-self-consistent":
                        self.assertIn('"releaseWatermarkCount": 0', result.stderr)
                        self.assertIn('"visibleOwnerLedgerMatches": true', result.stderr)
                        self.assertIn('"ownerHashFailureCount": 0', result.stderr)
                    elif label == "unhashed-owner-english-chrome":
                        self.assertIn('"unhashedOwnerCount": 1', result.stderr)
                    elif label == "css-generated-content":
                        self.assertIn('"pseudoContentFailureCount": 8', result.stderr)
                    elif label == "outside-article-visible-text":
                        self.assertIn('"outsideVisibleTextCount": 1', result.stderr)

    def test_no_javascript_remote_resource_or_fetch_capable_link(self):
        ir = sample_ir()
        ir["profile"]["matter_label"] = '<script src="https://cdn.invalid/a.js">x</script>'
        ir["slides"][0]["content"]["profile"]["matter_label"] = ir["profile"]["matter_label"]
        ir["slides"][0]["title"] = ir["profile"]["matter_label"]
        ir["semantic_inventory"] = build_source_inventory(ir["slides"])
        with tempfile.TemporaryDirectory() as raw:
            _, _, text = self.render(ir, Path(raw))

        lowered = text.lower()
        self.assertNotIn("<script", lowered)
        self.assertNotRegex(
            lowered,
            r"(?:src|href|action)\s*=\s*[\"']\s*(?:https?:)?//",
        )
        self.assertNotIn("https://cdn.invalid", lowered)
        self.assertIn("https&#58;//cdn.invalid", lowered)
        self.assertIn("connect-src &apos;none&apos;", lowered)
        self.assertIn("script-src &apos;none&apos;", lowered)

    def test_customer_text_is_escaped_and_unknown_internal_fields_are_not_rendered(self):
        ir = sample_ir()
        ir["slides"][1]["content"]["items"] = [
            {"text": '<img src=x onerror="alert(1)"> & 已核对'}
        ]
        ir["semantic_inventory"] = build_source_inventory(ir["slides"])
        ir["internal_notes"] = "INTERNAL-ONLY-SECRET-7429"
        with tempfile.TemporaryDirectory() as raw:
            _, _, text = self.render(ir, Path(raw))

        self.assertNotIn("<img src=x", text)
        self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt; &amp; 已核对", text)
        self.assertNotIn("INTERNAL-ONLY-SECRET-7429", text)

    def test_has_print_styles_inline_svg_and_no_hidden_dom(self):
        with tempfile.TemporaryDirectory() as raw:
            _, _, text = self.render(sample_ir(), Path(raw))

        lowered = text.lower()
        self.assertIn("@media print", lowered)
        self.assertIn("@page", lowered)
        self.assertIn("page-break-after: always", lowered)
        self.assertIn('<svg class="brand-mark"', lowered)
        self.assertNotIn("display: none", lowered)
        self.assertNotIn("visibility: hidden", lowered)
        self.assertNotIn("opacity: 0", lowered)
        self.assertNotRegex(lowered, r"\s(?:hidden|aria-hidden)(?:\s|=)")
        self.assertNotIn("<template", lowered)
        self.assertNotIn("<noscript", lowered)

    def test_verifier_rejects_comments_hidden_dom_and_unapproved_data_attributes(self):
        ir = sample_ir()
        mutations = (
            ("comment", lambda text: text.replace("<body>", "<!-- secret -->\n<body>", 1)),
            ("hidden", lambda text: text.replace('<div class="deck">', '<div class="deck" aria-hidden="true">', 1)),
            ("data", lambda text: text.replace('<div class="deck">', '<div class="deck" data-secret="internal">', 1)),
        )
        for label, mutate in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                output, _, text = self.render(ir, root)
                output.write_text(mutate(text), encoding="utf-8")
                with self.assertRaises(VerificationError):
                    verify_html(output, ir)

    def test_pii_canary_fails_before_any_filesystem_write(self):
        ir = sample_ir()
        ir["internal_notes"] = "PII_CANARY_DO_NOT_LEAK_13800138000"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "not-created"
            output = root / "report.html"
            with self.assertRaises(html_writer.HtmlRenderError):
                html_writer.render_html(ir, output)
            self.assertFalse(root.exists())

    def test_direct_html_writer_cannot_bypass_human_release_gate(self):
        ir = sample_ir()
        ir["release_state"] = "CLIENT_READY"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "not-created"
            output = root / "client-ready.html"
            with self.assertRaisesRegex(html_writer.HtmlRenderError, "REVIEW_DRAFT-only"):
                html_writer.render_html(ir, output)
            self.assertFalse(root.exists())

    def test_unknown_role_and_malformed_table_fail_closed_before_write(self):
        for mutate in ("role", "table"):
            ir = sample_ir()
            if mutate == "role":
                ir["slides"][2]["role"] = "custom_html"
            else:
                ir["slides"][4]["content"]["rows"][1]["cells"].append("extra")
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as raw:
                root = Path(raw) / "not-created"
                with self.assertRaises(html_writer.HtmlRenderError):
                    html_writer.render_html(ir, root / "report.html")
                self.assertFalse(root.exists())

    def test_atomic_replace_leaves_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "report.html"
            output.write_text("OLD", encoding="utf-8")
            _, receipt, text = self.render(sample_ir(), root, "report.html")
            self.assertNotEqual("OLD", text)
            self.assertEqual(receipt["size"], output.stat().st_size)
            self.assertEqual(["report.html"], sorted(path.name for path in root.iterdir()))

    def test_empty_optional_sections_are_omitted_from_customer_html(self):
        ir = sample_ir()
        ir["slides"][2]["content"]["chain"] = []
        ir["slides"][3]["content"]["undated_milestones"] = []
        ir["slides"][4]["content"]["amounts"] = []
        ir["slides"][4]["content"]["amount_notes"] = []
        ir["slides"][4]["content"]["evidence_index"] = []
        ir["slides"][5]["content"]["risks"] = []
        ir["slides"][6]["content"]["gaps"] = []
        ir["semantic_inventory"] = build_source_inventory(ir["slides"])
        with tempfile.TemporaryDirectory() as raw:
            _, _, text = self.render(ir, Path(raw))

        for heading in (
            "关系链条",
            "未定日期里程碑",
            "金额事项",
            "证据索引",
            "风险事项",
            "待补证据或信息",
        ):
            self.assertNotRegex(text, rf"<h3[^>]*>{re.escape(heading)}</h3>")
        self.assertRegex(text, r"<h3[^>]*>相关主体</h3>")
        self.assertRegex(text, r"<h3[^>]*>要件—证据矩阵</h3>")
        self.assertRegex(text, r"<h3[^>]*>程序阶段</h3>")
        self.assertRegex(text, r"<h3[^>]*>下一步行动</h3>")

    def test_verifier_detects_missing_duplicate_and_reordered_rendered_semantic_ids(self):
        ir = sample_ir()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output, _, text = self.render(ir, root)
            receipt = verify_html(output, ir)
            self.assertEqual("complete", receipt["semantic_completeness"]["status"])
            ids = re.findall(r'data-semantic-id="([^"]+)"', text)
            self.assertGreater(len(ids), 3)

            mutations = {
                "missing": text.replace(f' data-semantic-id="{ids[0]}"', "", 1),
                "duplicate": text.replace(
                    f'data-semantic-id="{ids[1]}"',
                    f'data-semantic-id="{ids[0]}"',
                    1,
                ),
                "reordered": text.replace(
                    f'data-semantic-id="{ids[0]}"',
                    'data-semantic-id="SEMANTIC-SWAP-TEMP"',
                    1,
                ).replace(
                    f'data-semantic-id="{ids[1]}"',
                    f'data-semantic-id="{ids[0]}"',
                    1,
                ).replace(
                    'data-semantic-id="SEMANTIC-SWAP-TEMP"',
                    f'data-semantic-id="{ids[1]}"',
                    1,
                ),
            }
            for name, mutated in mutations.items():
                with self.subTest(name=name):
                    bad = root / f"{name}.html"
                    bad.write_text(mutated, encoding="utf-8")
                    with self.assertRaisesRegex(VerificationError, "SILENT_TRUNCATION_DETECTED"):
                        verify_html(bad, ir)

    def test_verifier_rejects_unregistered_visible_text_and_semantic_inner_injection(self):
        ir = sample_ir()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output, _, text = self.render(ir, root)
            first_semantic = re.search(
                r'(<[^>]+\bdata-semantic-id="[^"]+"[^>]*>)', text
            )
            self.assertIsNotNone(first_semantic)
            mutations = {
                "unregistered-page-visible": re.sub(
                    r"(<article\b[^>]*>)",
                    r"\1<p>UNREGISTERED-PAGE-VISIBLE</p>",
                    text,
                    count=1,
                ),
                "semantic-inner-injection": text.replace(
                    first_semantic.group(1),
                    first_semantic.group(1) + "<span>SEMANTIC-INNER-SENTINEL</span>",
                    1,
                ),
            }
            for label, mutated in mutations.items():
                with self.subTest(label=label):
                    output.write_text(mutated, encoding="utf-8")
                    with self.assertRaisesRegex(
                        VerificationError, "SILENT_TRUNCATION_DETECTED"
                    ):
                        verify_html(output, ir)


if __name__ == "__main__":
    unittest.main()
