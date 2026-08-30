from __future__ import annotations

import copy
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import uuid
import zipfile
import xml.etree.ElementTree as ET

NS_A = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
CORE_NS_TEST = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
}

from jsonschema import Draft202012Validator


CANDIDATE = Path(__file__).resolve().parents[1]
PACKAGE = CANDIDATE / "package"
FIXTURE = PACKAGE / "fixtures" / "sample-case"
RUNNER = PACKAGE / "tools" / "run_client_delivery.py"
PPTX_WRITER = PACKAGE / "client_delivery" / "pptx_writer.py"
PYTHON_PPTX_AVAILABLE = importlib.util.find_spec("pptx") is not None
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
DETERMINISM_RUN_GAP_SECONDS = 3.2
sys.path.insert(0, str(PACKAGE))

from client_delivery.delivery_ir import _balanced_chunks, build_delivery_ir
from client_delivery.html_writer import render_html
from client_delivery.input_gate import GateError, load_inputs, strict_json_bytes
from client_delivery.pptx_writer import _close_presentation_default_text_style
from client_delivery.semantic_inventory import (
    SemanticInventoryError,
    build_source_inventory,
    require_source_inventory,
)
from client_delivery.verify import (
    VerificationError,
    _expected_pptx_objects,
    normalize_pptx,
    verify_html,
    verify_pptx,
)
from tools.run_client_delivery import emit_success_after_commit, verify_html_browser, verify_qa


def sample_inputs() -> dict:
    return load_inputs(
        case_id="SAMPLE-01",
        frozen07_dir=str(FIXTURE),
        text_pass_receipt=str(FIXTURE / "TEXT-PASS-RECEIPT.json"),
        delivery_profile=str(FIXTURE / "CLIENT-DELIVERY-PROFILE.json"),
    )


def synthetic_legacy_layout_inputs() -> dict:
    """Return synthetic-only coverage for the closed legacy frozen-07 layout."""

    inputs = sample_inputs()
    text = inputs["markdown_text"]

    def replace_section(title: str, next_title: str, body: str) -> None:
        nonlocal text
        text, count = re.subn(
            rf"(?ms)^## {re.escape(title)}$.*?(?=^## {re.escape(next_title)}$)",
            f"## {title}\n\n{body.rstrip()}\n\n",
            text,
            count=1,
        )
        if count != 1:
            raise AssertionError(f"synthetic fixture section missing:{title}")

    replace_section(
        "第一节　主体与角色",
        "第二节　合同与交易链",
        """| 角色 | 主体 | 说明 |
| --- | --- | --- |
| 原告 | 合成主体甲 | 说明****甲 |
| 被告 | 合成主体乙 | 说明乙 |
| 第三人 | 合成主体丙 | 说明丙 |
| 其他 | 合成主体丁 | 说明丁 |""",
    )
    replace_section(
        "第四节　款项与余额",
        "第五节　通知抗辩与期间",
        """| 口径 | 项目 | 金额（万元） | 说明 |
| --- | --- | --- | --- |
| 合成口径甲 | 合成项目甲 | -12.50 | 说明****甲 |
| 合成口径乙 | 合成项目乙 | 0.125 | 说明乙 |
| 合成口径丙 | 合成项目丙 | 88.00 | 说明丙 |
| 合成口径丁 | 合成项目丁 | 非数值待核**** | 说明丁 |

金额字段按源文本保留，不作换算。""",
    )
    replace_section(
        "第六节　要件-事实-证据矩阵",
        "第七节　证据索引",
        """| 要件 | 事实主张 | 对应证据 | 状态 | 备注 |
| --- | --- | --- | --- | --- |
| 合成要件甲 | 合成事实甲 | 合成证据甲 | 已核 | 备注待人工阅读 |
| 合成要件乙 | 合成事实乙 | 合成证据乙 | 待补 | 备注乙 |
| 合成要件丙 | 合成事实丙 | 合成证据丙 | 缺证 | 备注丙 |
| 合成要件丁 | 合成事实丁 | 合成证据丁 | 已核 | 备注含缺字但非状态 |
| 合成要件戊 | 合成事实戊 | 合成证据戊 | 已核 | 备注含待字但非状态 |""",
    )
    replace_section(
        "第七节　证据索引",
        "第八节　诉讼阶段计划",
        """- 合成证据项甲****
- 合成证据项乙
- 合成证据项丙
- 合成证据项丁""",
    )
    replace_section(
        "第八节　诉讼阶段计划",
        "第九节　风险与暂停事项",
        """| 阶段 | 主要动作 | 时点 |
| --- | --- | --- |
| 合成阶段甲 | 合成动作甲 | 合成时点甲 |
| 合成阶段乙 | 合成动作乙 | 合成时点乙 |
| 合成阶段丙 | 合成动作丙 | 合成时点丙 |
| 合成阶段丁 | 合成动作丁 | 合成时点丁 |""",
    )
    text, count = re.subn(
        r"(?ms)^## 第九节　风险与暂停事项$.*\Z",
        """## 第九节　风险与暂停事项

| 风险事项 | 等级 | 说明 | 处置 |
| --- | --- | --- | --- |
| 合成风险甲 | 高 | 合成说明甲 | 合成处置甲 |
| 合成风险乙 | 中 | 合成说明乙 | 合成处置乙 |
| 合成风险丙 | 低 | 合成说明丙 | 合成处置丙 |
| 合成风险丁 | 待核 | 合成说明丁 | 合成处置丁 |
""",
        text,
        count=1,
    )
    if count != 1:
        raise AssertionError("synthetic fixture section missing:A09")
    return {**inputs, "markdown_text": text}


def mutate_zip_member(source: Path, target: Path, member: str, mutate) -> None:
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(
        target, "w", compression=zipfile.ZIP_DEFLATED
    ) as changed:
        for info in original.infolist():
            payload = original.read(info)
            if info.filename == member:
                payload = mutate(payload)
            changed.writestr(info, payload)


class S2RuntimeTests(unittest.TestCase):
    def run_candidate(
        self,
        out: Path,
        run_id: str,
        formats: list[str] | None = None,
        env: dict[str, str] | None = None,
        profile: Path | None = None,
    ):
        command = [
            sys.executable,
            str(RUNNER),
            "--enable-client-delivery",
            "--case-id",
            "SAMPLE-01",
            "--frozen07-dir",
            str(FIXTURE),
            "--text-pass-receipt",
            str(FIXTURE / "TEXT-PASS-RECEIPT.json"),
            "--delivery-profile",
            str(profile or (FIXTURE / "CLIENT-DELIVERY-PROFILE.json")),
            "--out",
            str(out),
            "--run-id",
            run_id,
        ]
        for value in formats or []:
            command.extend(["--format", value])
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            env={**(env or os.environ), "PYTHONDONTWRITEBYTECODE": "1"},
            timeout=300,
        )

    def test_contract_schemas_are_valid(self):
        for path in sorted((CANDIDATE / "references" / "contracts").glob("*v*.schema.json")):
            with self.subTest(path=path.name):
                Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))

    def test_post_commit_status_pipe_failure_is_not_a_transaction_failure(self):
        with mock.patch("builtins.print", side_effect=BrokenPipeError):
            emit_success_after_commit({"ok": True, "release_state": "REVIEW_DRAFT"})

    def test_portable_pptx_dependency_doctor_and_missing_dependency_exit_three(self):
        healthy = subprocess.run(
            [sys.executable, str(RUNNER), "--dependency-doctor"],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            timeout=20,
        )
        self.assertEqual(0, healthy.returncode, healthy.stderr)
        report = json.loads(healthy.stdout.strip().splitlines()[-1])
        self.assertEqual("python-pptx", report["pptx"]["engine"])
        self.assertEqual("1.0.2", report["pptx"]["python_pptx_version"])
        self.assertEqual("python-playwright-chromium", report["html"]["engine"])
        self.assertEqual("1.59.0", report["html"]["playwright_version"])
        self.assertFalse(report["codex_runtime_required"])
        self.assertFalse(report["node_runtime_required"])

        unavailable = subprocess.run(
            [sys.executable, str(RUNNER), "--dependency-doctor"],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "S2_PPTX_FORCE_UNAVAILABLE": "1",
            },
            timeout=20,
        )
        self.assertEqual(3, unavailable.returncode)
        self.assertIn("python-pptx", unavailable.stderr)

    def test_direct_pptx_writer_cannot_bypass_human_release_gate(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ir_path = root / "client-ready.json"
            ir_path.write_text(
                json.dumps(
                    {"schema": "delivery-ir/1.0", "release_state": "CLIENT_READY"},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            output = root / "client-ready.pptx"
            qa = root / "qa"
            result = subprocess.run(
                [
                    sys.executable,
                    str(PPTX_WRITER),
                    "--input",
                    str(ir_path),
                    "--output",
                    str(output),
                    "--qa",
                    str(qa),
                ],
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                timeout=20,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("REVIEW_DRAFT-only", result.stderr)
            self.assertFalse(output.exists())
            self.assertFalse(qa.exists())

    def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(GateError):
                strict_json_bytes(raw, "probe")

    def test_sample_delivery_ir_is_sixteen_page_closed_and_schema_valid(self):
        ir = build_delivery_ir(sample_inputs(), PACKAGE)
        self.assertEqual(16, len(ir["slides"]))
        self.assertEqual(
            [
                "cover",
                "scope",
                "executive_summary",
                "relationship",
                "relationship",
                "timeline",
                "timeline",
                "timeline",
                "evidence_matrix",
                "evidence_matrix",
                "evidence_matrix",
                "stage_risk",
                "stage_risk",
                "next_steps",
                "next_steps",
                "scope",
            ],
            [slide["role"] for slide in ir["slides"]],
        )
        self.assertEqual("REVIEW_DRAFT", ir["release_state"])
        relationships = [slide for slide in ir["slides"] if slide["role"] == "relationship"]
        self.assertEqual(2, len(relationships))
        party_page = next(slide for slide in relationships if slide["content"]["parties"])
        chain_page = next(slide for slide in relationships if slide["content"]["chain"])
        self.assertEqual([], party_page["content"]["chain"])
        self.assertEqual(["A01"], party_page["source_refs"])
        self.assertEqual([], chain_page["content"]["parties"])
        self.assertEqual(["A02"], chain_page["source_refs"])
        self.assertTrue(
            all(not re.match(r"^\d+[.、．]", item["text"]) for item in chain_page["content"]["chain"])
        )
        stage_risk_pages = [slide for slide in ir["slides"] if slide["role"] == "stage_risk"]
        self.assertEqual(
            [("stage-plan-01", 2, 0), ("risk-register-01", 0, 2)],
            [
                (
                    slide["slide_id"],
                    len(slide["content"]["stages"]),
                    len(slide["content"]["risks"]),
                )
                for slide in stage_risk_pages
            ],
        )
        for slide in ir["slides"]:
            content = slide["content"]
            if slide["role"] == "evidence_matrix":
                self.assertEqual(
                    1,
                    sum(
                        bool(content[key])
                        for key in ("rows", "amounts", "amount_notes", "evidence_index")
                    ),
                )
            elif slide["role"] == "stage_risk":
                self.assertNotEqual(bool(content["stages"]), bool(content["risks"]))
            elif slide["role"] == "next_steps":
                self.assertNotEqual(bool(content["items"]), bool(content["gaps"]))
        semantic_ids = [item["semantic_id"] for item in ir["semantic_inventory"]]
        self.assertEqual(54, len(semantic_ids))
        self.assertEqual(len(semantic_ids), len(set(semantic_ids)))
        self.assertEqual(21, ir["source_consumption"]["total_projection_count"])
        self.assertEqual(14, ir["profile_consumption"]["total_projection_count"])
        self.assertEqual(19, ir["derived_consumption"]["total_projection_count"])
        self.assertEqual(54, ir["domain_projection_partition"]["partitioned_item_count"])
        self.assertEqual(0, ir["domain_projection_partition"]["unpartitioned_item_count"])
        self.assertEqual(ir["semantic_inventory"], build_delivery_ir(sample_inputs(), PACKAGE)["semantic_inventory"])
        self.assertEqual({f"A{index:02d}" for index in range(1, 10)}, {source["source_id"] for source in ir["sources"]})
        schema = json.loads((CANDIDATE / "references" / "contracts" / "delivery-ir-v1.schema.json").read_text(encoding="utf-8"))
        self.assertEqual([], list(Draft202012Validator(schema).iter_errors(ir)))

    def test_profile_consumption_closes_visible_occurrences_and_stale_rewrites(self):
        ir = build_delivery_ir(sample_inputs(), PACKAGE)
        ledger = ir["profile_consumption"]
        self.assertEqual("profile-consumption/1.0", ledger["schema"])
        self.assertEqual(14, ledger["candidate_item_count"])
        self.assertEqual(14, ledger["consumed_item_count"])
        self.assertEqual(14, ledger["total_projection_count"])
        self.assertEqual(100, ledger["coverage_percent"])
        self.assertEqual(0, ledger["unconsumed_item_count"])
        self.assertEqual(0, ledger["undeclared_duplicate_count"])
        self.assertEqual(5, ledger["excluded_control_count"])
        self.assertEqual(
            {
                "schema",
                "case_ref",
                "internal_case_id_sha256",
                "data_class",
                "release_state",
            },
            {item["field"] for item in ledger["excluded_controls"]},
        )
        self.assertTrue(
            all(
                item["excluded_reason"] == "non_customer_visible_control"
                for item in ledger["excluded_controls"]
            )
        )
        self.assertEqual(
            {("executive_summary", index) for index in range(3)},
            {
                (item["field"], item["source_index"])
                for item in ledger["items"]
                if item["field"] == "executive_summary"
            },
        )
        self.assertEqual(ir["semantic_inventory"], require_source_inventory(ir))

        baseline_profile_sha = ir["profile_sha256"]
        baseline_source_ledger = copy.deepcopy(ir["source_consumption"])
        for mutation in ("delete", "reorder", "whitespace"):
            stale = copy.deepcopy(ir)
            summary = next(
                slide
                for slide in stale["slides"]
                if slide["slide_id"] == "executive-summary-01"
            )["content"]["items"]
            if mutation == "delete":
                summary.pop(1)
            elif mutation == "reorder":
                summary[0], summary[1] = summary[1], summary[0]
            else:
                summary[0] += " "
            stale["semantic_inventory"] = build_source_inventory(stale["slides"])
            self.assertEqual(baseline_profile_sha, stale["profile_sha256"])
            self.assertEqual(baseline_source_ledger, stale["source_consumption"])
            with self.subTest(mutation=mutation), self.assertRaisesRegex(
                SemanticInventoryError, r"stale profile consumption projection"
            ):
                require_source_inventory(stale)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            profile = json.loads(
                (FIXTURE / "CLIENT-DELIVERY-PROFILE.json").read_text(
                    encoding="utf-8"
                )
            )
            profile["executive_summary"] = [
                "EXEC-DUPLICATE-EXACT",
                "EXEC-DUPLICATE-EXACT",
                *[f"EXEC-{index:02d}" for index in range(3, 17)],
            ]
            profile["next_steps"] = [
                "NEXT-DUPLICATE-EXACT",
                "NEXT-DUPLICATE-EXACT",
                *[f"NEXT-{index:02d}" for index in range(3, 25)],
            ]
            profile["scope_items"] = [
                "SCOPE-DUPLICATE-EXACT",
                "SCOPE-DUPLICATE-EXACT",
                *[f"SCOPE-{index:02d}" for index in range(3, 17)],
            ]
            profile_path = root / "max-profile.json"
            profile_path.write_text(
                json.dumps(profile, ensure_ascii=False), encoding="utf-8"
            )
            max_inputs = load_inputs(
                case_id="SAMPLE-01",
                frozen07_dir=str(FIXTURE),
                text_pass_receipt=str(FIXTURE / "TEXT-PASS-RECEIPT.json"),
                delivery_profile=str(profile_path),
            )
            max_ir = build_delivery_ir(max_inputs, PACKAGE)
            max_ledger = max_ir["profile_consumption"]
            self.assertEqual(61, max_ledger["candidate_item_count"])
            self.assertEqual(61, max_ledger["consumed_item_count"])
            self.assertEqual(61, max_ledger["total_projection_count"])
            for field in ("executive_summary", "next_steps", "scope_items"):
                duplicates = [
                    item
                    for item in max_ledger["items"]
                    if item["field"] == field and item["source_index"] in {0, 1}
                ]
                self.assertEqual([0, 1], [item["source_index"] for item in duplicates])
                self.assertEqual(1, len({item["source_sha256"] for item in duplicates}))
                self.assertEqual(
                    2,
                    len(
                        {
                            item["projection"]["semantic_id"]
                            for item in duplicates
                        }
                    ),
                )
            self.assertEqual(max_ir["semantic_inventory"], require_source_inventory(max_ir))

    def test_three_way_semantic_partition_rejects_unledgered_visible_items(self):
        ir = build_delivery_ir(sample_inputs(), PACKAGE)
        schema = json.loads(
            (
                CANDIDATE
                / "references"
                / "contracts"
                / "delivery-ir-v1.schema.json"
            ).read_text(encoding="utf-8")
        )

        def append_chain(candidate):
            slide = next(
                item
                for item in candidate["slides"]
                if item["role"] == "relationship" and item["content"]["chain"]
            )
            slide["content"]["chain"].append({"text": "UNLEDGERED-SOURCE-LIKE-CHAIN"})

        def append_timeline(candidate):
            slide = next(
                item
                for item in candidate["slides"]
                if item["role"] == "timeline"
                and len(item["content"]["events"]) < 4
            )
            slide["content"]["events"].append(
                {"date": "2026-08-15", "text": "UNLEDGERED-SOURCE-LIKE-EVENT"}
            )

        def append_evidence(candidate):
            slide = next(
                item
                for item in candidate["slides"]
                if item["role"] == "evidence_matrix"
                and item["content"]["evidence_index"]
            )
            slide["content"]["evidence_index"].append(
                {"text": "UNLEDGERED-SOURCE-LIKE-EVIDENCE"}
            )

        def append_risk(candidate):
            slide = next(
                item
                for item in candidate["slides"]
                if item["role"] == "stage_risk" and item["content"]["risks"]
            )
            slide["content"]["risks"].append(
                {"cells": ["X", "X", "UNLEDGERED-SOURCE-LIKE-RISK", "X"]}
            )

        def append_gap(candidate):
            slide = next(
                item
                for item in candidate["slides"]
                if item["role"] == "next_steps" and item["content"]["gaps"]
            )
            slide["content"]["gaps"].append("UNLEDGERED-SOURCE-LIKE-GAP")

        def append_executive(candidate):
            slide = next(
                item for item in candidate["slides"] if item["role"] == "executive_summary"
            )
            slide["content"]["items"].append("UNLEDGERED-PROFILE-EXECUTIVE")

        def append_next(candidate):
            slide = next(
                item
                for item in candidate["slides"]
                if item["slide_id"] == "next-actions-01"
            )
            slide["content"]["items"].append("UNLEDGERED-PROFILE-NEXT")

        def append_scope(candidate):
            slide = next(
                item for item in candidate["slides"] if item["slide_id"] == "scope-01"
            )
            slide["content"]["items"].append("UNLEDGERED-PROFILE-SCOPE")

        def mutate_title(candidate):
            candidate["slides"][1]["title"] += "-UNLEDGERED-TITLE"

        def add_executive_page(candidate):
            candidate["slides"].insert(
                3,
                {
                    "slide_id": "executive-summary-02",
                    "role": "executive_summary",
                    "title": "客户沟通摘要（续 2）",
                    "source_refs": ["A01"],
                    "content": {"items": ["UNLEDGERED-EXTRA-EXECUTIVE-PAGE"]},
                },
            )

        def add_next_page(candidate):
            candidate["slides"].insert(
                -1,
                {
                    "slide_id": "next-actions-02",
                    "role": "next_steps",
                    "title": "下一步行动（续 2）",
                    "source_refs": ["A08"],
                    "content": {
                        "items": ["UNLEDGERED-EXTRA-NEXT-PAGE"],
                        "gaps": [],
                    },
                },
            )

        def add_scope_page(candidate):
            candidate["slides"].append(
                {
                    "slide_id": "scope-02",
                    "role": "scope",
                    "title": "UNLEDGERED-EXTRA-SCOPE-PAGE",
                    "source_refs": ["A09"],
                    "content": {"items": ["UNLEDGERED-EXTRA-SCOPE-ITEM"]},
                }
            )

        mutations = {
            "relationship.chain": append_chain,
            "timeline.events": append_timeline,
            "evidence_index": append_evidence,
            "stage.risks": append_risk,
            "next_steps.gaps": append_gap,
            "profile.executive": append_executive,
            "profile.next": append_next,
            "profile.scope": append_scope,
            "slide.title": mutate_title,
            "extra.executive.page": add_executive_page,
            "extra.next.page": add_next_page,
            "extra.scope.page": add_scope_page,
        }
        for label, mutate in mutations.items():
            candidate = copy.deepcopy(ir)
            mutate(candidate)
            candidate["semantic_inventory"] = build_source_inventory(
                candidate["slides"]
            )
            self.assertEqual(
                [],
                list(Draft202012Validator(schema).iter_errors(candidate)),
                label,
            )
            with self.subTest(label=label), self.assertRaises(
                SemanticInventoryError
            ):
                require_source_inventory(candidate)

        no_law_inputs = sample_inputs()
        no_law_inputs["markdown_text"] = no_law_inputs["markdown_text"].replace(
            "全部法条引用未注入", "全部法律引用待核", 1
        )
        no_law_ir = build_delivery_ir(no_law_inputs, PACKAGE)
        notice = next(
            item
            for item in no_law_ir["derived_consumption"]["items"]
            if item["derived_id"] == "missing-legal-authority-notice"
        )
        self.assertEqual("missing_legal_authority_notice", notice["derived_reason"])
        self.assertEqual("risks", notice["projection"]["slot"])
        self.assertEqual(55, len(no_law_ir["semantic_inventory"]))
        self.assertEqual(20, no_law_ir["derived_consumption"]["candidate_item_count"])
        self.assertEqual(no_law_ir["semantic_inventory"], require_source_inventory(no_law_ir))

    @unittest.skipUnless(PYTHON_PPTX_AVAILABLE, "python-pptx runtime not configured")
    def test_portable_pptx_closes_twenty_one_pages_and_eighty_two_semantic_items(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            profile = json.loads(
                (FIXTURE / "CLIENT-DELIVERY-PROFILE.json").read_text(
                    encoding="utf-8"
                )
            )
            profile["executive_summary"].extend(
                f"EXECUTIVE-LOAD-{index:02d}" for index in range(4, 9)
            )
            profile["next_steps"].extend(
                f"NEXT-LOAD-{index:02d}" for index in range(4, 22)
            )
            profile_path = root / "twenty-one-profile.json"
            profile_path.write_text(
                json.dumps(profile, ensure_ascii=False), encoding="utf-8"
            )
            inputs = load_inputs(
                case_id="SAMPLE-01",
                frozen07_dir=str(FIXTURE),
                text_pass_receipt=str(FIXTURE / "TEXT-PASS-RECEIPT.json"),
                delivery_profile=str(profile_path),
            )
            ir = build_delivery_ir(inputs, PACKAGE)
            self.assertEqual(21, len(ir["slides"]))
            self.assertEqual(82, len(ir["semantic_inventory"]))
            self.assertEqual(37, ir["profile_consumption"]["candidate_item_count"])
            self.assertEqual(82, ir["domain_projection_partition"]["partitioned_item_count"])
            ir_path = root / "delivery-ir.json"
            ir_path.write_text(
                json.dumps(ir, ensure_ascii=False, sort_keys=True), encoding="utf-8"
            )
            output = root / "twenty-one-pages.pptx"
            qa = root / "qa"
            generated = subprocess.run(
                [
                    sys.executable,
                    str(PPTX_WRITER),
                    "--input",
                    str(ir_path),
                    "--output",
                    str(output),
                    "--qa",
                    str(qa),
                ],
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                timeout=240,
            )
            self.assertEqual(0, generated.returncode, generated.stderr)
            structure = normalize_pptx(output)
            receipt = verify_pptx(output, ir, structure_sha256=structure)
            qa_receipt = verify_qa(qa, ir)
            self.assertEqual(21, receipt["slide_count"])
            self.assertEqual(82, receipt["semantic_completeness"]["source_item_count"])
            self.assertEqual(82, receipt["semantic_completeness"]["rendered_item_count"])
            self.assertEqual("complete", receipt["semantic_completeness"]["status"])
            self.assertTrue(receipt["review_draft_visible_on_all_slides"])
            self.assertEqual(21, qa_receipt["slide_pngs"])
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(
                    21,
                    sum(
                        bool(re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", name))
                        for name in archive.namelist()
                    ),
                )

    def test_no_silent_truncation_uses_deterministic_pagination(self):
        inputs = sample_inputs()
        five_chain_text = inputs["markdown_text"].replace(
            "\n## 第三节　履行与交付链",
            "\n3. 补充交易节点03；\n4. 补充交易节点04；\n5. 补充交易节点05；\n\n## 第三节　履行与交付链",
        )
        five_chain_ir = build_delivery_ir(
            {**inputs, "markdown_text": five_chain_text}, PACKAGE
        )
        five_chain_pages = [
            slide
            for slide in five_chain_ir["slides"]
            if slide["role"] == "relationship" and slide["content"]["chain"]
        ]
        self.assertEqual(
            [3, 2], [len(slide["content"]["chain"]) for slide in five_chain_pages]
        )
        self.assertTrue(
            all(not slide["content"]["parties"] for slide in five_chain_pages)
        )

    @unittest.skipUnless(PYTHON_PPTX_AVAILABLE, "python-pptx runtime not configured")
    def test_mixed_dated_and_undated_anchor_closes_both_writer_inventories(self):
        inputs = sample_inputs()
        dated_a03 = "设备于2020-02-01交付并经样例承租人签收（样例签收单）。"
        sentinel = "UNDATED-SENTINEL-KEEP"
        mixed_text = inputs["markdown_text"].replace(
            dated_a03,
            f"{dated_a03}\n{sentinel}",
            1,
        )
        ir = build_delivery_ir({**inputs, "markdown_text": mixed_text}, PACKAGE)
        ledger = ir["source_consumption"]
        self.assertEqual("source-consumption/1.0", ledger["schema"])
        self.assertEqual(
            [f"A{index:02d}" for index in range(1, 10)], ledger["scope"]
        )
        self.assertEqual(100, ledger["coverage_percent"])
        self.assertEqual(0, ledger["unconsumed_item_count"])
        self.assertEqual(0, ledger["undeclared_duplicate_count"])
        self.assertEqual(ledger["excluded_item_count"], len(ledger["excluded_items"]))
        self.assertEqual(
            {f"A{index:02d}" for index in range(1, 10)},
            {
                item["source_id"]
                for item in ledger["excluded_items"]
                if item["excluded_reason"] == "anchor_title"
            },
        )
        self.assertLessEqual(
            {item["excluded_reason"] for item in ledger["excluded_items"]},
            {"anchor_title", "table_header", "table_separator"},
        )
        self.assertEqual(ledger["candidate_item_count"], ledger["consumed_item_count"])
        self.assertEqual(ledger["candidate_item_count"], len(ledger["items"]))
        source_keys = [
            (item["source_id"], item["source_locator"]) for item in ledger["items"]
        ]
        self.assertEqual(len(source_keys), len(set(source_keys)))
        projection_locations = [
            (projection["slide_id"], projection["slot"], projection["item_index"])
            for item in ledger["items"]
            for projection in item["projections"]
        ]
        self.assertEqual(len(projection_locations), len(set(projection_locations)))
        semantic_by_id = {
            item["semantic_id"]: item for item in ir["semantic_inventory"]
        }
        for item in ledger["items"]:
            self.assertGreaterEqual(len(item["projections"]), 1)
            for projection in item["projections"]:
                semantic = semantic_by_id[projection["semantic_id"]]
                self.assertEqual(projection["slide_id"], semantic["slide_id"])
                self.assertEqual(projection["slot"], semantic["slot"])
                self.assertEqual(projection["item_index"], semantic["item_index"])
                self.assertEqual(projection["content_sha256"], semantic["content_sha256"])

        timeline_slides = [
            slide for slide in ir["slides"] if slide["role"] == "timeline"
        ]
        source_values = [
            item["text"]
            for slide in timeline_slides
            for slot in ("events", "undated_milestones")
            for item in slide["content"][slot]
            if item["text"] in {dated_a03, sentinel}
        ]
        self.assertEqual([dated_a03, sentinel], source_values)
        self.assertEqual(2, len(source_values))
        self.assertEqual(2, len(set(source_values)))
        self.assertEqual(
            [sentinel],
            [
                item["text"]
                for item in timeline_slides[-1]["content"]["undated_milestones"]
                if item["text"] == sentinel
            ],
        )
        self.assertTrue(
            all(
                sentinel
                not in [item["text"] for item in slide["content"]["undated_milestones"]]
                for slide in timeline_slides[:-1]
            )
        )

        sentinel_items = [
            item
            for item in ir["semantic_inventory"]
            if item["slide_id"] == timeline_slides[-1]["slide_id"]
            and item["slot"] == "undated_milestones"
            and timeline_slides[-1]["content"]["undated_milestones"][
                item["item_index"]
            ]["text"]
            == sentinel
        ]
        self.assertEqual(1, len(sentinel_items))
        sentinel_id = sentinel_items[0]["semantic_id"]
        a03_records = [
            item for item in ledger["items"] if item["source_id"] == "A03"
        ]
        self.assertEqual(2, len(a03_records))
        by_source_hash = {item["source_sha256"]: item for item in a03_records}
        dated_record = by_source_hash[
            "sha256:" + hashlib.sha256(dated_a03.encode("utf-8")).hexdigest()
        ]
        sentinel_record = by_source_hash[
            "sha256:" + hashlib.sha256(sentinel.encode("utf-8")).hexdigest()
        ]
        self.assertEqual(
            ["dated"],
            [
                projection["mode"]
                for projection in dated_record["projections"]
                if projection["slot"] == "events"
            ],
        )
        self.assertEqual(1, len(sentinel_record["projections"]))
        self.assertEqual("undated", sentinel_record["projections"][0]["mode"])
        self.assertEqual(
            timeline_slides[-1]["slide_id"],
            sentinel_record["projections"][0]["slide_id"],
        )
        self.assertEqual(sentinel_id, sentinel_record["projections"][0]["semantic_id"])

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ir_path = root / "mixed-ir.json"
            ir_path.write_text(
                json.dumps(ir, ensure_ascii=False, sort_keys=True), encoding="utf-8"
            )
            pptx_path = root / "mixed.pptx"
            qa_path = root / "qa"
            generated = subprocess.run(
                [
                    sys.executable,
                    str(PPTX_WRITER),
                    "--input",
                    str(ir_path),
                    "--output",
                    str(pptx_path),
                    "--qa",
                    str(qa_path),
                ],
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                timeout=240,
            )
            self.assertEqual(0, generated.returncode, generated.stderr)
            pptx_receipt = verify_pptx(
                pptx_path,
                ir,
                structure_sha256=normalize_pptx(pptx_path),
            )
            self.assertEqual("complete", pptx_receipt["semantic_completeness"]["status"])
            with zipfile.ZipFile(pptx_path) as archive:
                self.assertEqual(
                    1,
                    sum(
                        archive.read(name).count(sentinel_id.encode("utf-8"))
                        for name in archive.namelist()
                        if name.endswith(".xml")
                    ),
                )

            html_path = root / "mixed.html"
            render_html(ir, html_path)
            html_receipt = verify_html(html_path, ir)
            self.assertEqual("complete", html_receipt["semantic_completeness"]["status"])
            self.assertEqual(
                1,
                html_path.read_text(encoding="utf-8").count(
                    f'data-semantic-id="{sentinel_id}"'
                ),
            )

    def test_extended_sources_are_all_present_after_pagination(self):
        inputs = sample_inputs()
        text = inputs["markdown_text"]
        extra_parties = "\n".join(
            f"| 扩展主体{i:02d} | 角色{i:02d} | 要点{i:02d} | 来源{i:02d} |"
            for i in range(1, 11)
        )
        extra_chain = "\n".join(
            f"{i + 2}. 扩展交易节点{i:02d}（2020-03-{i:02d}登记）；"
            for i in range(1, 11)
        )
        extra_matrix = "\n".join(
            f"| 扩展要件{i:02d} | 扩展事实{i:02d} | 扩展证据{i:02d} | 扩展缺口{i:02d} | 待核{i:02d} |"
            for i in range(1, 13)
        )
        extra_stages = "\n".join(
            f"| 扩展阶段{i:02d} | 扩展动作{i:02d} | 扩展出口{i:02d} |"
            for i in range(1, 10)
        )
        text = text.replace("\n## 第二节　合同与交易链", f"\n{extra_parties}\n\n## 第二节　合同与交易链")
        text = text.replace("\n## 第三节　履行与交付链", f"\n{extra_chain}\n\n## 第三节　履行与交付链")
        text = text.replace("\n## 第七节　证据索引", f"\n{extra_matrix}\n\n## 第七节　证据索引")
        text = text.replace("\n## 第九节　风险与暂停事项", f"\n{extra_stages}\n\n## 第九节　风险与暂停事项")
        extended = {**inputs, "markdown_text": text}
        ir = build_delivery_ir(extended, PACKAGE)
        visible = json.dumps(ir["slides"], ensure_ascii=False)
        for sentinel in ("扩展主体10", "扩展交易节点10", "扩展要件12", "扩展阶段09"):
            self.assertIn(sentinel, visible)
        self.assertGreater(len(ir["slides"]), 10)
        self.assertGreater(sum(slide["role"] == "timeline" for slide in ir["slides"]), 1)
        self.assertGreater(sum(slide["role"] == "evidence_matrix" for slide in ir["slides"]), 2)

    def test_full_source_consumption_routes_all_anchors_and_rejects_shape_drift(self):
        inputs = sample_inputs()
        ir = build_delivery_ir(inputs, PACKAGE)
        ledger = ir["source_consumption"]
        counts = Counter(item["source_id"] for item in ledger["items"])
        self.assertEqual(
            {
                "A01": 2,
                "A02": 2,
                "A03": 1,
                "A04": 2,
                "A05": 2,
                "A06": 2,
                "A07": 1,
                "A08": 2,
                "A09": 2,
            },
            dict(counts),
        )
        self.assertEqual(16, ledger["candidate_item_count"])
        self.assertEqual(16, ledger["consumed_item_count"])
        self.assertEqual(21, ledger["total_projection_count"])
        a06 = [item for item in ledger["items"] if item["source_id"] == "A06"]
        self.assertEqual(
            [["rows"], ["rows", "gaps"]],
            [[projection["slot"] for projection in item["projections"]] for item in a06],
        )
        visible = json.dumps(ir["slides"], ensure_ascii=False)
        self.assertNotIn("## 第一节", visible)
        self.assertNotIn("| --- |", visible)

        decimal_text = inputs["markdown_text"].replace(
            "\n## 第三节　履行与交付链",
            "\n2024.5万元NUM\n100．00元FULLWIDTH\n-100.00元NEGATIVE\n"
            "\n## 第三节　履行与交付链",
            1,
        ).replace(
            "样例证一合同8页 / 样例证二对账单2页。",
            "样例证一合同8页 / 样例证二对账单2页。\n"
            "100.00元NUM\n200．00元FULLWIDTH-EVID\n-200.00元EVIDNEG",
            1,
        )
        decimal_ir = build_delivery_ir(
            {**inputs, "markdown_text": decimal_text}, PACKAGE
        )
        decimal_visible = json.dumps(decimal_ir["slides"], ensure_ascii=False)
        self.assertIn("2024.5万元NUM", decimal_visible)
        self.assertIn("100.00元NUM", decimal_visible)
        self.assertIn("100．00元FULLWIDTH", decimal_visible)
        self.assertIn("200．00元FULLWIDTH-EVID", decimal_visible)
        self.assertIn("-100.00元NEGATIVE", decimal_visible)
        self.assertIn("-200.00元EVIDNEG", decimal_visible)
        self.assertNotIn('"5万元NUM"', decimal_visible)
        self.assertNotIn('"00元NUM"', decimal_visible)
        self.assertNotIn('"00元FULLWIDTH"', decimal_visible)
        self.assertNotIn('"00元FULLWIDTH-EVID"', decimal_visible)
        self.assertNotIn('"100.00元NEGATIVE"', decimal_visible)
        self.assertNotIn('"200.00元EVIDNEG"', decimal_visible)

        duplicate_line = "样例证一合同8页 / 样例证二对账单2页。"
        duplicate_ir = build_delivery_ir(
            {
                **inputs,
                "markdown_text": inputs["markdown_text"].replace(
                    duplicate_line,
                    f"{duplicate_line}\n{duplicate_line}",
                    1,
                ),
            },
            PACKAGE,
        )
        duplicate_a07 = [
            item
            for item in duplicate_ir["source_consumption"]["items"]
            if item["source_id"] == "A07"
        ]
        self.assertEqual(2, len(duplicate_a07))
        self.assertEqual(2, len({item["source_locator"] for item in duplicate_a07}))
        self.assertEqual(1, len({item["source_sha256"] for item in duplicate_a07}))
        self.assertEqual(
            2,
            len(
                {
                    projection["semantic_id"]
                    for item in duplicate_a07
                    for projection in item["projections"]
                }
            ),
        )

        extra_columns = {
            "A01": (
                "| 样例出租公司 | 出租人／原告 | 合成主体甲 | 样例合同 |",
                "| 样例出租公司 | 出租人／原告 | 合成主体甲 | 样例合同 | EXTRA |",
            ),
            "A04": (
                "| 到期未付租金 | 100,000.00 | 截至2021-06-30对账 |",
                "| 到期未付租金 | 100,000.00 | 截至2021-06-30对账 | EXTRA4 | EXTRA5 |",
            ),
            "A06": (
                "| 合同成立 | 2020-01-15签订 | 样例证一 | 无 | 已核验 |",
                "| 合同成立 | 2020-01-15签订 | 样例证一 | 无 | 已核验 | EXTRA |",
            ),
            "A08": (
                "| 一·立案 | 递交起诉状 | 法源终签 |",
                "| 一·立案 | 递交起诉状 | 法源终签 | EXTRA |",
            ),
            "A09": (
                "| 风险1 | 待人工法律复核 | 全部法条引用未注入 | 人工终签 |",
                "| 风险1 | 待人工法律复核 | 全部法条引用未注入 | 人工终签 | EXTRA |",
            ),
        }
        for anchor_id, (before, after) in extra_columns.items():
            with self.subTest(anchor_id=anchor_id), self.assertRaisesRegex(
                ValueError, rf"{anchor_id}第1行列数必须为"
            ):
                build_delivery_ir(
                    {
                        **inputs,
                        "markdown_text": inputs["markdown_text"].replace(
                            before, after, 1
                        ),
                    },
                    PACKAGE,
                )

        empty_sections = {
            "A01": ("第一节　主体与角色", "第二节　合同与交易链"),
            "A06": ("第六节　要件-事实-证据矩阵", "第七节　证据索引"),
            "A07": ("第七节　证据索引", "第八节　诉讼阶段计划"),
        }
        for anchor_id, (title, next_title) in empty_sections.items():
            empty_text = re.sub(
                rf"(?ms)^## {re.escape(title)}$.*?(?=^## {re.escape(next_title)}$)",
                f"## {title}\n\n",
                inputs["markdown_text"],
                count=1,
            )
            expected_error = (
                rf"{anchor_id}缺少固定表头"
                if anchor_id in {"A01", "A06"}
                else rf"源消费账锚无候选源项:{anchor_id}"
            )
            with self.subTest(empty_anchor=anchor_id), self.assertRaisesRegex(
                ValueError, expected_error
            ):
                build_delivery_ir(
                    {**inputs, "markdown_text": empty_text}, PACKAGE
                )

    def test_safe_parser_preserves_masks_and_requires_exact_table_structure(self):
        inputs = sample_inputs()
        mask_text = inputs["markdown_text"].replace(
            "2. 样例买卖合同（设备一台）。",
            "2. 账号6222****1234（2020-01-16登记）。",
            1,
        ).replace(
            "| 到期未付租金 | 100,000.00 | 截至2021-06-30对账 |",
            "| 到期未付租金****MASK | 100,000.00 | 截至2021-06-30对账 |",
            1,
        ).replace(
            "| 合同成立 | 2020-01-15签订 | 样例证一 | 无 | 已核验 |",
            "| 合同成立 | 2020-01-15签订 | 证据****脱敏-A06 | 无 | 已核验 |",
            1,
        ).replace(
            "样例证一合同8页 / 样例证二对账单2页。",
            "样例证一合同8页 / 样例证二对账单2页。\n证据****脱敏-A07",
            1,
        )
        mask_ir = build_delivery_ir(
            {**inputs, "markdown_text": mask_text}, PACKAGE
        )
        visible = json.dumps(mask_ir["slides"], ensure_ascii=False)
        self.assertEqual(2, visible.count("账号6222****1234"))
        self.assertEqual(2, visible.count("到期未付租金****MASK"))
        self.assertEqual(1, visible.count("证据****脱敏-A06"))
        self.assertEqual(1, visible.count("证据****脱敏-A07"))
        for leaked in (
            "账号62221234",
            "到期未付租金MASK",
            "证据脱敏-A06",
            "证据脱敏-A07",
        ):
            self.assertNotIn(leaked, visible)

        table_shapes = {
            "A01": (
                "| 主体 | 角色 | 要点 | 来源 |",
                "| --- | --- | --- | --- |",
            ),
            "A04": (
                "| 项目 | 金额（元） | 口径 |",
                "| --- | --- | --- |",
            ),
            "A06": (
                "| 要件 | 事实 | 证据 | 缺口 | 状态 |",
                "| --- | --- | --- | --- | --- |",
            ),
            "A08": (
                "| 阶段 | 动作 | 出口 |",
                "| --- | --- | --- |",
            ),
            "A09": (
                "| 编号 | 类别 | 内容 | 解除条件 |",
                "| --- | --- | --- | --- |",
            ),
        }
        for anchor_id, (header, separator) in table_shapes.items():
            with self.subTest(anchor_id=anchor_id, defect="missing-header"), self.assertRaisesRegex(
                ValueError, rf"{anchor_id}固定表头不匹配"
            ):
                build_delivery_ir(
                    {
                        **inputs,
                        "markdown_text": inputs["markdown_text"].replace(
                            f"{header}\n", "", 1
                        ),
                    },
                    PACKAGE,
                )
            with self.subTest(anchor_id=anchor_id, defect="pseudo-header"), self.assertRaisesRegex(
                ValueError, rf"{anchor_id}固定表头不匹配"
            ):
                build_delivery_ir(
                    {
                        **inputs,
                        "markdown_text": inputs["markdown_text"].replace(
                            header, header.replace("|", "| 伪列 |", 1), 1
                        ),
                    },
                    PACKAGE,
                )
            with self.subTest(anchor_id=anchor_id, defect="missing-separator"), self.assertRaisesRegex(
                ValueError, rf"{anchor_id}固定表头后缺少合法紧邻分隔行"
            ):
                build_delivery_ir(
                    {
                        **inputs,
                        "markdown_text": inputs["markdown_text"].replace(
                            f"{header}\n{separator}", header, 1
                        ),
                    },
                    PACKAGE,
                )

        with self.assertRaisesRegex(ValueError, r"A01存在额外或错位分隔行"):
            build_delivery_ir(
                {
                    **inputs,
                    "markdown_text": inputs["markdown_text"].replace(
                        "| --- | --- | --- | --- |",
                        "| --- | --- | --- | --- |\n| --- | --- | --- | --- |",
                        1,
                    ),
                },
                PACKAGE,
            )
        with self.assertRaisesRegex(ValueError, r"A03存在未路由子标题"):
            build_delivery_ir(
                {
                    **inputs,
                    "markdown_text": inputs["markdown_text"].replace(
                        "设备于2020-02-01交付并经样例承租人签收（样例签收单）。",
                        "## 子标题-SILENT\n设备于2020-02-01交付并经样例承租人签收（样例签收单）。",
                        1,
                    ),
                },
                PACKAGE,
            )

        same_day_text = inputs["markdown_text"].replace(
            "\n## 第三节　履行与交付链",
            "\n3. ZZZ-FIRST-IN-SOURCE（2020-03-01登记）；\n"
            "4. AAA-SECOND-IN-SOURCE（2020-03-01登记）；\n\n"
            "## 第三节　履行与交付链",
            1,
        )
        same_day_ir = build_delivery_ir(
            {**inputs, "markdown_text": same_day_text}, PACKAGE
        )
        same_day_events = [
            event["text"]
            for slide in same_day_ir["slides"]
            if slide["role"] == "timeline"
            for event in slide["content"]["events"]
            if event["date"] == "2020-03-01"
        ]
        self.assertEqual(
            ["ZZZ-FIRST-IN-SOURCE（2020-03-01登记）；", "AAA-SECOND-IN-SOURCE（2020-03-01登记）；"],
            same_day_events,
        )

    def test_closed_legacy_layout_preserves_native_semantics_and_rejects_drift(self):
        inputs = synthetic_legacy_layout_inputs()
        ir = build_delivery_ir(inputs, PACKAGE)
        source_schema = ir["source_schema"]
        self.assertEqual("legacy-frozen07-v1", source_schema["variant"])
        self.assertEqual(
            {
                "A01": ["角色", "主体", "说明"],
                "A04": ["口径", "项目", "金额（万元）", "说明"],
                "A06": ["要件", "事实主张", "对应证据", "状态", "备注"],
                "A08": ["阶段", "主要动作", "时点"],
                "A09": ["风险事项", "等级", "说明", "处置"],
            },
            source_schema["table_headers"],
        )

        ledger = ir["source_consumption"]
        six_anchors = {"A01", "A04", "A06", "A07", "A08", "A09"}
        six_items = [
            item for item in ledger["items"] if item["source_id"] in six_anchors
        ]
        six_exclusions = [
            item
            for item in ledger["excluded_items"]
            if item["source_id"] in six_anchors
        ]
        self.assertEqual(26, len(six_items))
        self.assertEqual(16, len(six_exclusions))
        self.assertEqual(32, sum(len(item["projections"]) for item in six_items))
        self.assertEqual(100, ledger["coverage_percent"])
        self.assertEqual(0, ledger["unconsumed_item_count"])

        party_texts = [
            party["text"]
            for slide in ir["slides"]
            if slide["role"] == "relationship"
            for party in slide["content"]["parties"]
        ]
        self.assertEqual(
            "角色=原告 / 主体=合成主体甲 / 说明=说明****甲",
            party_texts[0],
        )
        canonical = build_delivery_ir(sample_inputs(), PACKAGE)
        canonical_party = next(
            party["text"]
            for slide in canonical["slides"]
            if slide["role"] == "relationship"
            for party in slide["content"]["parties"]
        )
        self.assertTrue(canonical_party.startswith("主体=样例出租公司 / 角色="))
        self.assertIn(" / 来源=样例合同", canonical_party)

        amount_rows = [
            row["cells"]
            for slide in ir["slides"]
            if slide["role"] == "evidence_matrix"
            for row in slide["content"]["amounts"]
        ]
        self.assertEqual(
            [
                ["合成口径甲", "合成项目甲", "-12.50", "说明****甲"],
                ["合成口径乙", "合成项目乙", "0.125", "说明乙"],
                ["合成口径丙", "合成项目丙", "88.00", "说明丙"],
                ["合成口径丁", "合成项目丁", "非数值待核****", "说明丁"],
            ],
            amount_rows,
        )
        amount_notes = [
            note["text"]
            for slide in ir["slides"]
            if slide["role"] == "evidence_matrix"
            for note in slide["content"]["amount_notes"]
        ]
        self.assertEqual(["金额字段按源文本保留，不作换算。"], amount_notes)
        self.assertFalse(
            any(
                amount_notes[0] in event["text"]
                for slide in ir["slides"]
                if slide["role"] == "timeline"
                for slot in ("events", "undated_milestones")
                for event in slide["content"][slot]
            )
        )
        note_source = next(
            item
            for item in ledger["items"]
            if item["source_id"] == "A04" and item["source_kind"] == "prose_line"
        )
        self.assertEqual(
            ["amount_notes"],
            [projection["slot"] for projection in note_source["projections"]],
        )

        gaps = [
            value
            for slide in ir["slides"]
            if slide["role"] == "next_steps"
            for value in slide["content"]["gaps"]
        ]
        self.assertEqual(2, len(gaps))
        self.assertTrue(any("待补" in value for value in gaps))
        self.assertTrue(any("缺证" in value for value in gaps))
        self.assertFalse(any("备注待人工阅读" in value for value in gaps))
        self.assertFalse(any("备注含缺字但非状态" in value for value in gaps))
        self.assertFalse(any("备注含待字但非状态" in value for value in gaps))

        a07 = [item for item in ledger["items"] if item["source_id"] == "A07"]
        self.assertEqual(4, len(a07))
        self.assertTrue(all(item["source_kind"] == "prose_line" for item in a07))
        self.assertTrue(
            all(
                [projection["slot"] for projection in item["projections"]]
                == ["evidence_index"]
                for item in a07
            )
        )
        raw_a07 = [
            "- 合成证据项甲****",
            "- 合成证据项乙",
            "- 合成证据项丙",
            "- 合成证据项丁",
        ]
        self.assertEqual(
            ["sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest() for value in raw_a07],
            [item["source_sha256"] for item in a07],
        )
        self.assertEqual(
            [value.removeprefix("- ") for value in raw_a07],
            [
                item["text"]
                for slide in ir["slides"]
                if slide["role"] == "evidence_matrix"
                for item in slide["content"]["evidence_index"]
            ],
        )
        schema = json.loads(
            (CANDIDATE / "references/contracts/delivery-ir-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual([], list(Draft202012Validator(schema).iter_errors(ir)))
        self.assertEqual(ir["semantic_inventory"], require_source_inventory(ir))

        hybrid = inputs["markdown_text"].replace(
            "| 风险事项 | 等级 | 说明 | 处置 |",
            "| 编号 | 类别 | 内容 | 解除条件 |",
            1,
        )
        with self.assertRaisesRegex(ValueError, r"固定表头变体混用"):
            build_delivery_ir({**inputs, "markdown_text": hybrid}, PACKAGE)

        header_drifts = {
            "A01": ("| 角色 | 主体 | 说明 |", "| 主体 | 角色 | 说明 |"),
            "A04": ("| 口径 | 项目 | 金额（万元） | 说明 |", "| 项目 | 口径 | 金额（万元） | 说明 |"),
            "A06": ("| 要件 | 事实主张 | 对应证据 | 状态 | 备注 |", "| 要件 | 事实 | 对应证据 | 状态 | 备注 |"),
            "A08": ("| 阶段 | 主要动作 | 时点 |", "| 阶段 | 时点 | 主要动作 |"),
            "A09": ("| 风险事项 | 等级 | 说明 | 处置 |", "| 风险 | 等级 | 说明 | 处置 |"),
        }
        for anchor_id, (before, after) in header_drifts.items():
            with self.subTest(header_drift=anchor_id), self.assertRaisesRegex(
                ValueError, rf"{anchor_id}固定表头不匹配"
            ):
                build_delivery_ir(
                    {
                        **inputs,
                        "markdown_text": inputs["markdown_text"].replace(
                            before, after, 1
                        ),
                    },
                    PACKAGE,
                )

        row_width_drifts = {
            "A01": (
                "| 原告 | 合成主体甲 | 说明****甲 |",
                "| 原告 | 合成主体甲 |",
            ),
            "A04": (
                "| 合成口径甲 | 合成项目甲 | -12.50 | 说明****甲 |",
                "| 合成口径甲 | 合成项目甲 | -12.50 | 说明****甲 | EXTRA |",
            ),
            "A06": (
                "| 合成要件甲 | 合成事实甲 | 合成证据甲 | 已核 | 备注待人工阅读 |",
                "| 合成要件甲 | 合成事实甲 | 合成证据甲 | 已核 |",
            ),
            "A08": (
                "| 合成阶段甲 | 合成动作甲 | 合成时点甲 |",
                "| 合成阶段甲 | 合成动作甲 | 合成时点甲 | EXTRA |",
            ),
            "A09": (
                "| 合成风险甲 | 高 | 合成说明甲 | 合成处置甲 |",
                "| 合成风险甲 | 高 | 合成说明甲 |",
            ),
        }
        for anchor_id, (before, after) in row_width_drifts.items():
            with self.subTest(row_width=anchor_id), self.assertRaisesRegex(
                ValueError, rf"{anchor_id}第1行列数必须为"
            ):
                build_delivery_ir(
                    {
                        **inputs,
                        "markdown_text": inputs["markdown_text"].replace(
                            before, after, 1
                        ),
                    },
                    PACKAGE,
                )

        wrong_separator = inputs["markdown_text"].replace(
            "| 口径 | 项目 | 金额（万元） | 说明 |\n| --- | --- | --- | --- |",
            "| 口径 | 项目 | 金额（万元） | 说明 |\n| --- | --- | --- |",
            1,
        )
        with self.assertRaisesRegex(ValueError, r"A04固定表头后缺少合法紧邻分隔行"):
            build_delivery_ir({**inputs, "markdown_text": wrong_separator}, PACKAGE)

        note = "金额字段按源文本保留，不作换算。"
        note_drifts = {
            "missing": inputs["markdown_text"].replace(f"\n\n{note}", "", 1),
            "duplicate": inputs["markdown_text"].replace(note, f"{note}\n{note}", 1),
            "no-blank-boundary": inputs["markdown_text"].replace(f"\n\n{note}", f"\n{note}", 1),
            "forced-into-table": inputs["markdown_text"].replace(
                f"\n\n{note}", "\n| 金额说明 | 空 | 空 | 空 |", 1
            ),
        }
        for label, mutated in note_drifts.items():
            with self.subTest(note_drift=label), self.assertRaisesRegex(
                ValueError, r"A04"
            ):
                build_delivery_ir({**inputs, "markdown_text": mutated}, PACKAGE)

        a07_table = inputs["markdown_text"].replace(
            "- 合成证据项乙", "| 合成证据项乙 |", 1
        )
        with self.assertRaisesRegex(ValueError, r"A07仅允许实质散文行"):
            build_delivery_ir({**inputs, "markdown_text": a07_table}, PACKAGE)

    @unittest.skipUnless(PYTHON_PPTX_AVAILABLE, "python-pptx runtime not configured")
    def test_legacy_headers_are_identical_in_html_pptx_and_forgery_fails_closed(self):
        ir = build_delivery_ir(synthetic_legacy_layout_inputs(), PACKAGE)
        expected_headers = ir["source_schema"]["table_headers"]
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            html_path = root / "legacy.html"
            render_html(ir, html_path)
            html_receipt = verify_html(html_path, ir)
            self.assertEqual("complete", html_receipt["semantic_completeness"]["status"])
            html_text = html_path.read_text(encoding="utf-8")
            for anchor_id in ("A04", "A06", "A08", "A09"):
                for header in expected_headers[anchor_id]:
                    self.assertIn(f"<th>{header}</th>", html_text)
            self.assertNotIn("<th>金额（元）</th>", html_text)
            self.assertNotIn("<th>出口</th>", html_text)
            self.assertNotIn("<th>解除条件</th>", html_text)

            ir_path = root / "legacy-ir.json"
            ir_path.write_text(
                json.dumps(ir, ensure_ascii=False, sort_keys=True), encoding="utf-8"
            )
            pptx_path = root / "legacy.pptx"
            qa = root / "legacy-qa"
            generated = subprocess.run(
                [
                    sys.executable,
                    str(PPTX_WRITER),
                    "--input",
                    str(ir_path),
                    "--output",
                    str(pptx_path),
                    "--qa",
                    str(qa),
                ],
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                timeout=240,
            )
            self.assertEqual(0, generated.returncode, generated.stderr)
            receipt = verify_pptx(
                pptx_path, ir, structure_sha256=normalize_pptx(pptx_path)
            )
            self.assertEqual("complete", receipt["semantic_completeness"]["status"])
            with zipfile.ZipFile(pptx_path) as archive:
                visible_xml = b"".join(
                    archive.read(name)
                    for name in archive.namelist()
                    if name.startswith("ppt/slides/slide") and name.endswith(".xml")
                ).decode("utf-8")
            for anchor_id in ("A04", "A06", "A08", "A09"):
                for header in expected_headers[anchor_id]:
                    self.assertIn(f">{header}<", visible_xml)

            forged = copy.deepcopy(ir)
            forged["source_schema"]["table_headers"]["A04"][2] = "金额（元）"
            forged_html = root / "forged.html"
            with self.assertRaisesRegex(ValueError, r"源布局表头与变体不一致"):
                render_html(forged, forged_html)
            self.assertFalse(forged_html.exists())
            forged_ir = root / "forged-ir.json"
            forged_ir.write_text(
                json.dumps(forged, ensure_ascii=False, sort_keys=True), encoding="utf-8"
            )
            forged_pptx = root / "forged.pptx"
            forged_qa = root / "forged-qa"
            rejected = subprocess.run(
                [
                    sys.executable,
                    str(PPTX_WRITER),
                    "--input",
                    str(forged_ir),
                    "--output",
                    str(forged_pptx),
                    "--qa",
                    str(forged_qa),
                ],
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                timeout=60,
            )
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("源布局表头与变体不一致", rejected.stderr)
            self.assertFalse(forged_pptx.exists())
            self.assertFalse(forged_qa.exists())

    def test_timeline_events_are_balanced_and_undated_items_only_use_final_page(self):
        expected = {
            7: [4, 3],
            8: [4, 4],
            9: [3, 3, 3],
            10: [4, 3, 3],
            11: [4, 4, 3],
        }
        for count, page_sizes in expected.items():
            with self.subTest(count=count):
                pages = _balanced_chunks(list(range(count)), 4)
                self.assertEqual(page_sizes, [len(page) for page in pages])
                self.assertEqual(list(range(count)), [item for page in pages for item in page])
                self.assertNotIn(1, [len(page) for page in pages])
                self.assertLessEqual(
                    max(len(page) for page in pages) - min(len(page) for page in pages),
                    1,
                )

        inputs = sample_inputs()
        text = inputs["markdown_text"].replace(
            "| 到期未付租金 | 100,000.00 | 截至2021-06-30对账 |",
            "| 到期未付租金 | 100,000.00 | 对账日期待核 |",
        )
        added = "\n".join(
            f"{index + 2}. 补充事件（2022-01-{index:02d}发生）；"
            for index in range(1, 4)
        )
        text = text.replace(
            "\n## 第三节　履行与交付链",
            f"\n{added}\n\n## 第三节　履行与交付链",
        )
        ir = build_delivery_ir({**inputs, "markdown_text": text}, PACKAGE)
        timelines = [slide for slide in ir["slides"] if slide["role"] == "timeline"]
        self.assertEqual([4, 3, 0], [len(slide["content"]["events"]) for slide in timelines])
        self.assertEqual(0, len(timelines[0]["content"]["undated_milestones"]))
        self.assertGreater(len(timelines[-1]["content"]["undated_milestones"]), 0)
        self.assertTrue(
            all(
                not slide["content"]["undated_milestones"]
                for slide in timelines[:-1]
            )
        )

        for event_count, added_count in ((5, 1), (6, 2)):
            with self.subTest(event_count=event_count, undated=True):
                dense_added = "\n".join(
                    f"{index + 2}. 密集事件（2023-02-{index:02d}发生）；"
                    for index in range(1, added_count + 1)
                )
                dense_text = inputs["markdown_text"].replace(
                    "| 到期未付租金 | 100,000.00 | 截至2021-06-30对账 |",
                    "| 到期未付租金 | 100,000.00 | 对账日期待核 |",
                ).replace(
                    "\n## 第三节　履行与交付链",
                    f"\n{dense_added}\n\n## 第三节　履行与交付链",
                )
                dense_ir = build_delivery_ir(
                    {**inputs, "markdown_text": dense_text}, PACKAGE
                )
                dense_timelines = [
                    slide for slide in dense_ir["slides"]
                    if slide["role"] == "timeline"
                ]
                expected_events = [3, 2, 0] if event_count == 5 else [3, 3, 0]
                self.assertEqual(expected_events, [len(slide["content"]["events"]) for slide in dense_timelines])
                self.assertTrue(
                    dense_timelines[-1]["content"]["undated_milestones"]
                )
                self.assertTrue(
                    all(
                        not slide["content"]["undated_milestones"]
                        for slide in dense_timelines[:-1]
                    )
                )

    def test_wrong_case_and_client_released_profile_fail_closed(self):
        with self.assertRaises(GateError):
            load_inputs(
                case_id="OTHER",
                frozen07_dir=str(FIXTURE),
                text_pass_receipt=str(FIXTURE / "TEXT-PASS-RECEIPT.json"),
                delivery_profile=str(FIXTURE / "CLIENT-DELIVERY-PROFILE.json"),
            )
        with tempfile.TemporaryDirectory() as raw:
            profile = json.loads((FIXTURE / "CLIENT-DELIVERY-PROFILE.json").read_text(encoding="utf-8"))
            profile["release_state"] = "CLIENT_RELEASED"
            path = Path(raw) / "profile.json"
            path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(GateError):
                load_inputs(
                    case_id="SAMPLE-01",
                    frozen07_dir=str(FIXTURE),
                    text_pass_receipt=str(FIXTURE / "TEXT-PASS-RECEIPT.json"),
                    delivery_profile=str(path),
                )

            profile = json.loads(
                (FIXTURE / "CLIENT-DELIVERY-PROFILE.json").read_text(
                    encoding="utf-8"
                )
            )
            profile["brand_profile"] = {
                "schema": "litigation-brand-profile/v1",
                "name": "无效未消费主题参数",
                "theme": "neutral-law-firm",
            }
            brand_path = Path(raw) / "profile-brand.json"
            brand_path.write_text(
                json.dumps(profile, ensure_ascii=False), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                GateError, r"交付profile含未注册字段:brand_profile"
            ):
                load_inputs(
                    case_id="SAMPLE-01",
                    frozen07_dir=str(FIXTURE),
                    text_pass_receipt=str(FIXTURE / "TEXT-PASS-RECEIPT.json"),
                    delivery_profile=str(brand_path),
                )

    def test_profile_materials_as_of_uses_real_calendar(self):
        base = json.loads(
            (FIXTURE / "CLIENT-DELIVERY-PROFILE.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for value in ("2026-02-30", "2025-02-29"):
                profile = {**base, "materials_as_of": value}
                path = root / f"invalid-{value}.json"
                path.write_text(
                    json.dumps(profile, ensure_ascii=False), encoding="utf-8"
                )
                with self.subTest(value=value), self.assertRaisesRegex(
                    GateError, r"materials_as_of不是有效日历日期"
                ):
                    load_inputs(
                        case_id="SAMPLE-01",
                        frozen07_dir=str(FIXTURE),
                        text_pass_receipt=str(FIXTURE / "TEXT-PASS-RECEIPT.json"),
                        delivery_profile=str(path),
                    )

            leap_path = root / "valid-2024-02-29.json"
            leap_path.write_text(
                json.dumps(
                    {**base, "materials_as_of": "2024-02-29"},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            loaded = load_inputs(
                case_id="SAMPLE-01",
                frozen07_dir=str(FIXTURE),
                text_pass_receipt=str(FIXTURE / "TEXT-PASS-RECEIPT.json"),
                delivery_profile=str(leap_path),
            )
            self.assertEqual("2024-02-29", loaded["profile"]["materials_as_of"])

    @unittest.skipUnless(
        PLAYWRIGHT_CHROME_AVAILABLE, "system Python Playwright/Chrome not configured"
    )
    def test_html_only_runner_without_runtime_node_is_portable(self):
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw) / "bundle"
            env = {key: value for key, value in os.environ.items() if key not in {"RUNTIME_NODE", "RUNTIME_NODE_MODULES", "RUNTIME_BIN_DIR"}}
            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--enable-client-delivery",
                    "--case-id",
                    "SAMPLE-01",
                    "--frozen07-dir",
                    str(FIXTURE),
                    "--text-pass-receipt",
                    str(FIXTURE / "TEXT-PASS-RECEIPT.json"),
                    "--delivery-profile",
                    str(FIXTURE / "CLIENT-DELIVERY-PROFILE.json"),
                    "--out",
                    str(out),
                    "--format",
                    "html",
                    "--run-id",
                    "S2-TEST-HTML",
                ],
                capture_output=True,
                text=True,
                env={**env, "PYTHONDONTWRITEBYTECODE": "1"},
                timeout=30,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue((out / "client-briefing.REVIEW-DRAFT.html").is_file())
            receipt = json.loads(
                (out / "internal-audit" / "html-validation.json").read_text(
                    encoding="utf-8"
                )
            )
            doctor = receipt["browser_layout"]["dependency_doctor"]
            self.assertEqual("python-playwright-chromium", doctor["engine"])
            self.assertEqual("1.59.0", doctor["playwright_version"])
            self.assertFalse(doctor["codex_runtime_required"])
            self.assertFalse(doctor["node_runtime_required"])
            self.assertEqual([], list(Path(raw).glob(".bundle.*.failure.json")))

    def test_html_missing_playwright_or_chrome_exits_three_and_commits_nothing(self):
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw) / "bundle"
            result = self.run_candidate(
                out,
                "S2-TEST-HTML-DEPENDENCY-HOLD",
                ["html"],
                env={**os.environ, "S2_HTML_QA_FORCE_UNAVAILABLE": "1"},
            )
            self.assertEqual(3, result.returncode, result.stderr)
            self.assertFalse(out.exists())
            receipts = list(Path(raw).glob(".bundle.*.failure.json"))
            self.assertEqual(1, len(receipts))
            failure = json.loads(receipts[0].read_text(encoding="utf-8"))
            self.assertEqual("ENGINE_UNAVAILABLE", failure["failures"][0]["failure_code"])
            self.assertEqual("html", failure["failures"][0]["format"])
            self.assertTrue(failure["formal_output_unchanged"])

    @unittest.skipUnless(
        PLAYWRIGHT_CHROME_AVAILABLE, "system Python Playwright/Chrome not configured"
    )
    def test_html_only_runtime_closes_screen_print_and_stage_risk_pages(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            out = root / "bundle"
            result = self.run_candidate(out, "S2-TEST-HTML-RUNTIME", ["html"])
            self.assertEqual(0, result.returncode, result.stderr)
            receipt = json.loads(
                (out / "internal-audit" / "html-validation.json").read_text(
                    encoding="utf-8"
                )
            )
            browser = receipt["browser_layout"]
            self.assertEqual("pass", browser["status"])
            self.assertEqual("python-playwright-chromium", browser["engine"])
            self.assertEqual(0, browser["network_requests"])
            self.assertEqual(0, browser["screen_article_overflow_px"])
            self.assertEqual(0, browser["screen_semantic_overflow_px"])
            self.assertEqual(0, browser["print_article_overflow_px"])
            self.assertEqual(0, browser["print_semantic_overflow_px"])
            self.assertEqual(16, browser["print_page_count"])
            html_path = out / "client-briefing.REVIEW-DRAFT.html"
            html_text = html_path.read_text(encoding="utf-8")
            stage_risk_articles = re.findall(
                r'<article class="slide role-stage_risk"[^>]*>.*?</article>',
                html_text,
                re.DOTALL,
            )
            self.assertEqual(2, len(stage_risk_articles))
            self.assertIn("程序阶段", stage_risk_articles[0])
            self.assertNotIn("风险事项", stage_risk_articles[0])
            self.assertIn("风险事项", stage_risk_articles[1])
            self.assertNotIn("程序阶段", stage_risk_articles[1])

            ir = json.loads(
                (out / "internal-audit" / "delivery-ir.json").read_text(
                    encoding="utf-8"
                )
            )
            screen_bad = root / "screen-overflow.html"
            screen_bad.write_text(
                html_text.replace(
                    "</head>",
                    "<style>@media screen {.slide{min-height:792px!important}}</style></head>",
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                VerificationError, r"HTML_BROWSER_LAYOUT_INVALID:.*screen: article overflow"
            ):
                verify_html_browser(root, screen_bad, ir)

            print_bad = root / "print-overflow.html"
            print_bad_article = stage_risk_articles[0].replace(
                "<h2 ", '<h2 class="qa-overflow-probe" ', 1
            )
            self.assertNotEqual(stage_risk_articles[0], print_bad_article)
            print_bad.write_text(
                html_text.replace(
                    "</head>",
                    "<style>.qa-overflow-probe{position:absolute;left:72px;top:100px;height:20px}"
                    "@media print{.qa-overflow-probe{top:745px;height:45px}}</style></head>",
                    1,
                ).replace(
                    stage_risk_articles[0],
                    print_bad_article,
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                VerificationError, r"HTML_BROWSER_LAYOUT_INVALID:.*print: article overflow"
            ):
                verify_html_browser(root, print_bad, ir)

    @unittest.skipUnless(PYTHON_PPTX_AVAILABLE, "python-pptx runtime not configured")
    def test_pptx_relationship_pages_and_balanced_timeline_layout(self):
        inputs = sample_inputs()
        text = inputs["markdown_text"].replace(
            "| 到期未付租金 | 100,000.00 | 截至2021-06-30对账 |",
            "| 到期未付租金 | 100,000.00 | 对账日期待核 |",
        )
        added = "\n".join(
            f"{index + 2}. 补充事件（2022-01-{index:02d}发生）；"
            for index in range(1, 3)
        )
        text = text.replace(
            "\n## 第三节　履行与交付链",
            f"\n{added}\n\n## 第三节　履行与交付链",
        )
        ir = build_delivery_ir({**inputs, "markdown_text": text}, PACKAGE)
        timeline_indexes = [
            index for index, slide in enumerate(ir["slides"])
            if slide["role"] == "timeline"
        ]
        self.assertEqual(
            [3, 3, 0],
            [len(ir["slides"][index]["content"]["events"]) for index in timeline_indexes],
        )
        self.assertTrue(ir["slides"][timeline_indexes[-1]]["content"]["undated_milestones"])
        long_text = (
            "双方围绕设备采购、融资租赁、交付验收、租金支付、担保责任及通知送达"
            "形成连续事实链，本项仅忠实呈现冻结底稿中的时间、行为与证据指向，具体"
            "金额、责任范围和法律结论均待指定律师结合原始凭证复核。"
        )
        dated_template = ir["slides"][timeline_indexes[0]]
        for item_index, event in enumerate(dated_template["content"]["events"]):
            event["text"] = f"{long_text}（三项版事件{item_index + 1}）"
        extra_timeline_slides = []
        for count in (2, 3, 4):
            slide = copy.deepcopy(dated_template)
            slide["slide_id"] = f"timeline-fixture-{count:02d}"
            slide["title"] = f"关键事件时间线（{count}项长文本版式）"
            slide["content"]["events"] = [
                {
                    "date": f"2023-{count:02d}-{index:02d}",
                    "text": f"{long_text}（{count}项版事件{index}）",
                }
                for index in range(1, count + 1)
            ]
            slide["content"]["undated_milestones"] = []
            extra_timeline_slides.append(slide)
        first_timeline = timeline_indexes[0]
        ir["slides"] = (
            ir["slides"][:first_timeline]
            + extra_timeline_slides
            + ir["slides"][first_timeline:]
        )
        relationship_indexes = [
            index for index, slide in enumerate(ir["slides"])
            if slide["role"] == "relationship"
        ]
        relationship_index = relationship_indexes[0]
        party_template = next(
            ir["slides"][index]
            for index in relationship_indexes
            if ir["slides"][index]["content"]["parties"]
        )
        chain_template = next(
            ir["slides"][index]
            for index in relationship_indexes
            if ir["slides"][index]["content"]["chain"]
        )
        relationship_slides = []
        for count in range(2, 7):
            slide = copy.deepcopy(party_template)
            slide["slide_id"] = f"relationship-parties-fixture-{count:02d}"
            slide["title"] = f"案件主体（{count}方）"
            slide["content"]["parties"] = [
                {"text": f"合成主体{index:02d}"} for index in range(1, count + 1)
            ]
            slide["content"]["chain"] = []
            relationship_slides.append(slide)
        long_chain_text = (
            "出租人依据融资租赁合同向供应商支付设备价款，供应商按承租人指定地点"
            "交付并由承租人验收，承租人随后按约支付租金；该陈述仅忠实呈现冻结底稿"
            "中的交易步骤与证据指向，具体付款、交付、验收及责任承担仍待指定律师结合"
            "合同原件、付款凭证、验收材料和送达记录逐项复核。"
        )
        chain_items = [
            {"text": f"{long_chain_text}（交易链原文等价项{index}）"}
            for index in range(1, 6)
        ]
        for index, page in enumerate((chain_items[:3], chain_items[3:]), 1):
            slide = copy.deepcopy(chain_template)
            slide["slide_id"] = f"relationship-chain-fixture-{index:02d}"
            slide["title"] = "交易链条" + (f"（续 {index}）" if index > 1 else "")
            slide["content"]["parties"] = []
            slide["content"]["chain"] = page
            relationship_slides.append(slide)
        ir["slides"] = (
            ir["slides"][:relationship_index]
            + relationship_slides
            + ir["slides"][relationship_indexes[-1] + 1 :]
        )
        ir["semantic_inventory"] = build_source_inventory(ir["slides"])

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            runtime = root / "runtime"
            runtime.mkdir()
            writer = runtime / "pptx_writer.py"
            shutil.copy2(PPTX_WRITER, writer)
            delivery_ir_path = root / "delivery-ir.json"
            delivery_ir_path.write_text(
                json.dumps(ir, ensure_ascii=False, sort_keys=True), encoding="utf-8"
            )
            output = root / "relationship-counts.pptx"
            result = subprocess.run(
                [
                    sys.executable,
                    str(writer),
                    "--input",
                    str(delivery_ir_path),
                    "--output",
                    str(output),
                    "--qa",
                    str(root / "qa"),
                ],
                capture_output=True,
                text=True,
                timeout=240,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(0, result.returncode, result.stderr)
            # This test deliberately fabricates extra slides after the
            # production DeliveryIR build to stress only the native geometry
            # verifier.  It must not counterfeit a source-before production
            # ledger for those synthetic items, so verify it through the
            # explicit legacy/layout-fixture schema path instead.
            verification_ir = copy.deepcopy(ir)
            verification_ir["schema"] = "client-delivery-ir/v1"
            structure_sha256 = normalize_pptx(output)
            receipt = verify_pptx(
                output, verification_ir, structure_sha256=structure_sha256
            )
            qa_receipt = verify_qa(root / "qa", ir)
            self.assertEqual("pass", qa_receipt["timeline_text_capacity"])
            self.assertEqual(15, qa_receipt["timeline_text_boxes"])
            self.assertEqual("pass", qa_receipt["relationship_chain_text_capacity"])
            self.assertEqual(5, qa_receipt["relationship_chain_text_boxes"])
            relationship_metrics = [
                item for item in receipt["slide_metrics"]
                if item["role"] == "relationship"
            ]
            self.assertEqual(7, len(relationship_metrics))
            self.assertEqual([0] * 7, [item["connectors"] for item in relationship_metrics])
            self.assertEqual(
                ["parties"] * 5 + ["chain"] * 2,
                [item["relationship_layout"]["mode"] for item in relationship_metrics],
            )
            self.assertEqual(
                [2, 3, 4, 5, 6],
                [
                    item["relationship_layout"]["party_count"]
                    for item in relationship_metrics
                    if item["relationship_layout"]["mode"] == "parties"
                ],
            )
            self.assertEqual(
                [3, 2],
                [
                    item["relationship_layout"]["chain_count"]
                    for item in relationship_metrics
                    if item["relationship_layout"]["mode"] == "chain"
                ],
            )
            self.assertTrue(
                all(
                    item["relationship_layout"]["status"] == "pass"
                    and item["relationship_layout"]["visible_chain_numbering"] is False
                    for item in relationship_metrics
                )
            )
            timeline_metrics = [
                item for item in receipt["slide_metrics"]
                if item["role"] == "timeline"
            ]
            self.assertEqual(
                [2, 3, 4, 3, 3, 0],
                [item["timeline_layout"]["event_count"] for item in timeline_metrics],
            )
            self.assertTrue(
                all(
                    item["timeline_layout"]["status"] == "pass"
                    and item["timeline_layout"]["date_single_line_guard"]
                    == "wrap-none-and-width-pass"
                    and (
                        item["timeline_layout"]["minimum_date_inner_width_points"]
                        is None
                        or item["timeline_layout"]["minimum_date_inner_width_points"] >= 114
                    )
                    for item in timeline_metrics
                )
            )
            for layout_path in sorted((root / "qa").glob("slide-*.layout.json")):
                layout_text = layout_path.read_text(encoding="utf-8")
                self.assertNotRegex(
                    layout_text,
                    r'"(?:overflow|clipped)"\s*:\s*true',
                    layout_path.name,
                )

            def find_shape(document: ET.Element, prefix: str) -> ET.Element:
                ns = {
                    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
                    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
                }
                matches = []
                for shape in document.findall(".//p:sp", ns):
                    properties = shape.find("./p:nvSpPr/p:cNvPr", ns)
                    if properties is not None and (
                        properties.attrib.get("name") == prefix
                        or properties.attrib.get("name", "").startswith(prefix + "|")
                    ):
                        matches.append(shape)
                self.assertEqual(1, len(matches), prefix)
                return matches[0]

            def shape_transform(shape: ET.Element) -> tuple[ET.Element, ET.Element]:
                ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
                transform = shape.find("./p:spPr/a:xfrm", {**ns, "p": "http://schemas.openxmlformats.org/presentationml/2006/main"})
                self.assertIsNotNone(transform)
                offset = transform.find("a:off", ns)
                extent = transform.find("a:ext", ns)
                self.assertIsNotNone(offset)
                self.assertIsNotNone(extent)
                return offset, extent

            four_slide_index = next(
                index for index, slide in enumerate(ir["slides"])
                if slide["role"] == "timeline" and len(slide["content"]["events"]) == 4
            )
            four_slide_id = ir["slides"][four_slide_index]["slide_id"]

            def overlap_date_and_text(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                date_offset, _ = shape_transform(
                    find_shape(document, f"{four_slide_id}:event-date:0")
                )
                text_offset, _ = shape_transform(
                    find_shape(document, f"{four_slide_id}:event-text:0")
                )
                date_offset.attrib["x"] = text_offset.attrib["x"]
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def overlap_adjacent_rows(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                for slot in ("event-date", "event-text"):
                    first_offset, _ = shape_transform(
                        find_shape(document, f"{four_slide_id}:{slot}:0")
                    )
                    second_offset, _ = shape_transform(
                        find_shape(document, f"{four_slide_id}:{slot}:1")
                    )
                    second_offset.attrib["y"] = first_offset.attrib["y"]
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def move_guide_through_text(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                guide_offset, _ = shape_transform(
                    find_shape(document, f"{four_slide_id}:timeline-guide")
                )
                text_offset, text_extent = shape_transform(
                    find_shape(document, f"{four_slide_id}:event-text:0")
                )
                guide_offset.attrib["x"] = str(
                    int(text_offset.attrib["x"]) + int(text_extent.attrib["cx"]) // 2
                )
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def narrow_date_below_lo_safe_width(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                _, date_extent = shape_transform(
                    find_shape(document, f"{four_slide_id}:event-date:0")
                )
                # Restore the former 105pt outer width (93pt after margins),
                # which LibreOffice demonstrably wraps for YYYY-MM-DD.
                date_extent.attrib["cx"] = str(140 * 9525)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def reenable_date_wrapping(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                date_shape = find_shape(document, f"{four_slide_id}:event-date:0")
                body_properties = date_shape.find(
                    "./p:txBody/a:bodyPr",
                    {
                        "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
                        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
                    },
                )
                self.assertIsNotNone(body_properties)
                body_properties.attrib["wrap"] = "square"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            slide_member = f"ppt/slides/slide{four_slide_index + 1}.xml"
            for name, mutation, message in (
                ("date-text-overlap", overlap_date_and_text, "日期与正文重叠"),
                ("adjacent-overlap", overlap_adjacent_rows, "相邻事件框重叠"),
                ("guide-crosses-text", move_guide_through_text, "guide穿越文字"),
                (
                    "date-lo-safe-width",
                    narrow_date_below_lo_safe_width,
                    "日期列LO-safe净宽不足",
                ),
                (
                    "date-wrap-enabled",
                    reenable_date_wrapping,
                    "日期单行禁止换行门缺失",
                ),
            ):
                bad_layout = root / f"{name}.pptx"
                mutate_zip_member(output, bad_layout, slide_member, mutation)
                with self.subTest(name=name), self.assertRaisesRegex(
                    VerificationError, message
                ):
                    verify_pptx(bad_layout, verification_ir)

            chain_slide_index = next(
                index
                for index, slide in enumerate(ir["slides"])
                if slide["role"] == "relationship"
                and len(slide["content"]["chain"]) == 3
            )
            chain_slide_id = ir["slides"][chain_slide_index]["slide_id"]

            def overlap_chain_marker_and_text(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                marker_offset, _ = shape_transform(
                    find_shape(document, f"{chain_slide_id}:chain-marker:0")
                )
                text_offset, _ = shape_transform(
                    find_shape(document, f"{chain_slide_id}:chain-text:0")
                )
                marker_offset.attrib["x"] = text_offset.attrib["x"]
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def overlap_chain_rows(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                for slot in ("chain-row", "chain-marker", "chain-text"):
                    first_offset, _ = shape_transform(
                        find_shape(document, f"{chain_slide_id}:{slot}:0")
                    )
                    second_offset, _ = shape_transform(
                        find_shape(document, f"{chain_slide_id}:{slot}:1")
                    )
                    second_offset.attrib["y"] = first_offset.attrib["y"]
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def move_chain_row_outside_safe_bounds(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                for slot, left_px in (
                    ("chain-row", 0),
                    ("chain-marker", 10),
                    ("chain-text", 34),
                ):
                    offset, _ = shape_transform(
                        find_shape(document, f"{chain_slide_id}:{slot}:0")
                    )
                    offset.attrib["x"] = str(left_px * 9525)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def add_visible_chain_number(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                body = find_shape(document, f"{chain_slide_id}:chain-text:0")
                text_node = body.find(
                    ".//{http://schemas.openxmlformats.org/drawingml/2006/main}t"
                )
                self.assertIsNotNone(text_node)
                text_node.text = "01 " + (text_node.text or "")
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            chain_member = f"ppt/slides/slide{chain_slide_index + 1}.xml"
            for name, mutation, message in (
                (
                    "chain-marker-text-overlap",
                    overlap_chain_marker_and_text,
                    "marker与正文未形成独立同行列",
                ),
                ("chain-adjacent-overlap", overlap_chain_rows, "相邻chain行重叠"),
                (
                    "chain-safe-bounds",
                    move_chain_row_outside_safe_bounds,
                    "对象越出安全区",
                ),
                (
                    "chain-visible-number",
                    add_visible_chain_number,
                    "PPTX_VISIBLE_OBJECT_LEDGER_INVALID",
                ),
            ):
                bad_chain_layout = root / f"{name}.pptx"
                mutate_zip_member(output, bad_chain_layout, chain_member, mutation)
                with self.subTest(name=name), self.assertRaisesRegex(
                    VerificationError, message
                ):
                    verify_pptx(bad_chain_layout, verification_ir)

            bad_qa = root / "bad-qa"
            shutil.copytree(root / "qa", bad_qa)
            four_layout = bad_qa / f"slide-{four_slide_index + 1:02d}.layout.json"
            layout_document = json.loads(four_layout.read_text(encoding="utf-8"))
            event_element = next(
                element
                for element in layout_document["elements"]
                if element.get("name", "").startswith(f"{four_slide_id}:event-text:0")
            )
            event_element["textLayout"]["lineCount"] = 99
            four_layout.write_text(
                json.dumps(layout_document, ensure_ascii=False), encoding="utf-8"
            )
            with self.assertRaisesRegex(VerificationError, "文字容量不足"):
                verify_qa(bad_qa, ir)

            small_font_qa = root / "small-font-qa"
            shutil.copytree(root / "qa", small_font_qa)
            small_font_layout = (
                small_font_qa / f"slide-{four_slide_index + 1:02d}.layout.json"
            )
            small_font_document = json.loads(
                small_font_layout.read_text(encoding="utf-8")
            )
            small_font_element = next(
                element
                for element in small_font_document["elements"]
                if element.get("name", "").startswith(
                    f"{four_slide_id}:event-text:0"
                )
            )
            small_font_element["resolvedFontSize"] = 21.2
            small_font_layout.write_text(
                json.dumps(small_font_document, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(VerificationError, "实际字号不足|正文字号小于16"):
                verify_qa(small_font_qa, ir)

            bad_chain_qa = root / "bad-chain-qa"
            shutil.copytree(root / "qa", bad_chain_qa)
            chain_layout_path = (
                bad_chain_qa / f"slide-{chain_slide_index + 1:02d}.layout.json"
            )
            chain_layout_document = json.loads(
                chain_layout_path.read_text(encoding="utf-8")
            )
            chain_element = next(
                element
                for element in chain_layout_document["elements"]
                if element.get("name", "").startswith(
                    f"{chain_slide_id}:chain-text:0"
                )
            )
            chain_element["textLayout"]["lineCount"] = 99
            chain_layout_path.write_text(
                json.dumps(chain_layout_document, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(VerificationError, "文字容量不足"):
                verify_qa(bad_chain_qa, ir)

            small_chain_font_qa = root / "small-chain-font-qa"
            shutil.copytree(root / "qa", small_chain_font_qa)
            small_chain_layout_path = (
                small_chain_font_qa
                / f"slide-{chain_slide_index + 1:02d}.layout.json"
            )
            small_chain_document = json.loads(
                small_chain_layout_path.read_text(encoding="utf-8")
            )
            small_chain_element = next(
                element
                for element in small_chain_document["elements"]
                if element.get("name", "").startswith(
                    f"{chain_slide_id}:chain-text:0"
                )
            )
            small_chain_element["resolvedFontSize"] = 21.2
            small_chain_layout_path.write_text(
                json.dumps(small_chain_document, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(VerificationError, "实际字号不足|正文字号小于16"):
                verify_qa(small_chain_font_qa, ir)

            extreme_ir = copy.deepcopy(ir)
            extreme_chain_slide = extreme_ir["slides"][chain_slide_index]
            extreme_chain_slide["content"]["chain"][0]["text"] = long_chain_text * 12
            extreme_ir["semantic_inventory"] = build_source_inventory(
                extreme_ir["slides"]
            )
            extreme_ir_path = root / "extreme-delivery-ir.json"
            extreme_ir_path.write_text(
                json.dumps(extreme_ir, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            extreme_output = root / "extreme-chain.pptx"
            extreme_qa = root / "extreme-qa"
            extreme_result = subprocess.run(
                [
                    sys.executable,
                    str(writer),
                    "--input",
                    str(extreme_ir_path),
                    "--output",
                    str(extreme_output),
                    "--qa",
                    str(extreme_qa),
                ],
                capture_output=True,
                text=True,
                timeout=240,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(0, extreme_result.returncode, extreme_result.stderr)
            normalize_pptx(extreme_output)
            extreme_verification_ir = copy.deepcopy(extreme_ir)
            extreme_verification_ir["schema"] = "client-delivery-ir/v1"
            verify_pptx(extreme_output, extreme_verification_ir)
            with self.assertRaisesRegex(
                VerificationError, "布局导出报告溢出|文字容量不足"
            ):
                verify_qa(extreme_qa, extreme_ir)
            extreme_layout = json.loads(
                (
                    extreme_qa
                    / f"slide-{chain_slide_index + 1:02d}.layout.json"
                ).read_text(encoding="utf-8")
            )
            extreme_element = next(
                element
                for element in extreme_layout["elements"]
                if element.get("name", "").startswith(
                    f"{chain_slide_id}:chain-text:0"
                )
            )
            self.assertEqual(22, extreme_element["resolvedFontSize"])

            def add_unauthorized_connector(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                shape_tree = document.find(
                    ".//{http://schemas.openxmlformats.org/presentationml/2006/main}spTree"
                )
                self.assertIsNotNone(shape_tree)
                ET.SubElement(
                    shape_tree,
                    "{http://schemas.openxmlformats.org/presentationml/2006/main}cxnSp",
                )
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            bad = root / "unauthorized-connector.pptx"
            mutate_zip_member(
                output,
                bad,
                f"ppt/slides/slide{relationship_index + 1}.xml",
                add_unauthorized_connector,
            )
            with self.assertRaisesRegex(
                VerificationError, "PPTX_VISIBLE_OBJECT_LEDGER_INVALID|未授权connector"
            ):
                verify_pptx(bad, verification_ir)

    @unittest.skipUnless(
        PYTHON_PPTX_AVAILABLE and PLAYWRIGHT_CHROME_AVAILABLE,
        "python-pptx and system Python Playwright/Chrome not configured",
    )
    def test_pptx_default_and_dual_are_raw_byte_reproducible_and_atomic(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            default_out = root / "default"
            repeated_out = root / "repeated"
            dual_out = root / "dual"
            default = self.run_candidate(default_out, "S2-TEST-PPTX-DEFAULT")
            self.assertGreaterEqual(DETERMINISM_RUN_GAP_SECONDS, 3.0)
            time.sleep(DETERMINISM_RUN_GAP_SECONDS)
            repeated = self.run_candidate(repeated_out, "S2-TEST-PPTX-REPEATED")
            dual = self.run_candidate(dual_out, "S2-TEST-PPTX-DUAL", ["pptx", "html"])
            self.assertEqual(0, default.returncode, default.stderr)
            self.assertEqual(0, repeated.returncode, repeated.stderr)
            self.assertEqual(0, dual.returncode, dual.stderr)
            self.assertEqual(
                {"ARTIFACT-MANIFEST.json", "client-briefing.REVIEW-DRAFT.pptx", "internal-audit"},
                {path.name for path in default_out.iterdir()},
            )
            self.assertEqual(
                {
                    "ARTIFACT-MANIFEST.json",
                    "client-briefing.REVIEW-DRAFT.pptx",
                    "client-briefing.REVIEW-DRAFT.html",
                    "internal-audit",
                },
                {path.name for path in dual_out.iterdir()},
            )
            first = json.loads((default_out / "internal-audit" / "pptx-validation.json").read_text(encoding="utf-8"))
            repeated_receipt = json.loads(
                (repeated_out / "internal-audit" / "pptx-validation.json").read_text(
                    encoding="utf-8"
                )
            )
            second = json.loads((dual_out / "internal-audit" / "pptx-validation.json").read_text(encoding="utf-8"))
            self.assertEqual(
                "python_pptx_1_0_2_canonical_zip_raw_byte_identical",
                first["determinism_mode"],
            )
            first_pptx = default_out / "client-briefing.REVIEW-DRAFT.pptx"
            repeated_pptx = repeated_out / "client-briefing.REVIEW-DRAFT.pptx"
            self.assertEqual(first_pptx.read_bytes(), repeated_pptx.read_bytes())
            self.assertEqual(first["sha256"], repeated_receipt["sha256"])
            self.assertEqual(
                first["sha256"], hashlib.sha256(first_pptx.read_bytes()).hexdigest()
            )
            self.assertEqual(first["structure_sha256"], second["structure_sha256"])
            self.assertEqual(16, first["slide_count"])
            with zipfile.ZipFile(first_pptx) as archive:
                infos = archive.infolist()
                self.assertEqual(sorted(info.filename for info in infos), [info.filename for info in infos])
                self.assertTrue(all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in infos))
                self.assertTrue(all(info.compress_type == zipfile.ZIP_DEFLATED for info in infos))
                self.assertTrue(all(info.create_system == 3 for info in infos))
                self.assertTrue(all(info.external_attr == (0o100600 << 16) for info in infos))

            idempotent = root / "idempotent.pptx"
            idempotent.write_bytes(first_pptx.read_bytes())
            idempotent_structure = normalize_pptx(idempotent)
            self.assertEqual(first_pptx.read_bytes(), idempotent.read_bytes())
            self.assertEqual(first["structure_sha256"], idempotent_structure)

            changed_profile = json.loads(
                (FIXTURE / "CLIENT-DELIVERY-PROFILE.json").read_text(encoding="utf-8")
            )
            changed_profile["client_label"] += "（语义变更）"
            changed_profile_path = root / "changed-profile.json"
            changed_profile_path.write_text(
                json.dumps(changed_profile, ensure_ascii=False), encoding="utf-8"
            )
            changed_out = root / "changed"
            changed = self.run_candidate(
                changed_out,
                "S2-TEST-PPTX-SEMANTIC-CHANGE",
                profile=changed_profile_path,
            )
            self.assertEqual(0, changed.returncode, changed.stderr)
            changed_pptx = changed_out / "client-briefing.REVIEW-DRAFT.pptx"
            self.assertNotEqual(
                hashlib.sha256(first_pptx.read_bytes()).hexdigest(),
                hashlib.sha256(changed_pptx.read_bytes()).hexdigest(),
            )
            manifest = json.loads((dual_out / "ARTIFACT-MANIFEST.json").read_text(encoding="utf-8"))
            self.assertEqual(["pptx", "html"], manifest["requested"])
            self.assertEqual(["pptx", "html"], [item["format"] for item in manifest["produced"]])
            self.assertTrue(manifest["requested_equals_produced"])
            self.assertFalse(manifest["partial_success"])

    @unittest.skipUnless(PYTHON_PPTX_AVAILABLE, "python-pptx runtime not configured")
    def test_pptx_deterministic_canonicalizer_fails_closed_on_ambiguous_ooxml(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            out = root / "valid"
            result = self.run_candidate(out, "S2-TEST-DETERMINISM-NEGATIVE")
            self.assertEqual(0, result.returncode, result.stderr)
            source = out / "client-briefing.REVIEW-DRAFT.pptx"

            def duplicate_relationship(payload: bytes) -> bytes:
                relation_ns = (
                    "http://schemas.openxmlformats.org/package/2006/relationships"
                )
                document = ET.fromstring(payload)
                relation = document.find(f"{{{relation_ns}}}Relationship")
                self.assertIsNotNone(relation)
                duplicate = ET.SubElement(
                    document,
                    f"{{{relation_ns}}}Relationship",
                    dict(relation.attrib),
                )
                duplicate.attrib["Id"] = "rId9999"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            duplicate = root / "duplicate-relationship.pptx"
            mutate_zip_member(
                source,
                duplicate,
                "ppt/slides/_rels/slide1.xml.rels",
                duplicate_relationship,
            )
            with self.assertRaisesRegex(VerificationError, "重复语义relationship"):
                normalize_pptx(duplicate)

            def dangling_reference(payload: bytes) -> bytes:
                changed, count = re.subn(
                    rb'r:id="rId\d{4}"', b'r:id="rId9999"', payload, count=1
                )
                self.assertEqual(1, count)
                return changed

            dangling = root / "dangling-reference.pptx"
            mutate_zip_member(
                source,
                dangling,
                "ppt/presentation.xml",
                dangling_reference,
            )
            with self.assertRaisesRegex(VerificationError, "悬空引用"):
                normalize_pptx(dangling)

            def unknown_shape_context(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                ET.SubElement(
                    document,
                    "{http://schemas.microsoft.com/office/drawing/2014/main}creationId",
                    {"id": "{" + str(uuid.uuid4()).upper() + "}"},
                )
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            unknown = root / "unknown-creation-context.pptx"
            mutate_zip_member(
                source,
                unknown,
                "ppt/presentation.xml",
                unknown_shape_context,
            )
            with self.assertRaisesRegex(VerificationError, "未知上下文"):
                normalize_pptx(unknown)

            p14_namespace = "http://schemas.microsoft.com/office/powerpoint/2010/main"

            def duplicate_p14_owner(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                existing = document.find(f".//{{{p14_namespace}}}creationId")
                self.assertIsNotNone(existing)
                ET.SubElement(
                    document,
                    f"{{{p14_namespace}}}creationId",
                    {"val": existing.attrib["val"]},
                )
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            duplicate_p14 = root / "duplicate-p14-owner.pptx"
            mutate_zip_member(
                source,
                duplicate_p14,
                "ppt/slideMasters/slideMaster1.xml",
                duplicate_p14_owner,
            )
            with self.assertRaisesRegex(VerificationError, "p14 creationId位于未知上下文或计数异常"):
                normalize_pptx(duplicate_p14)

            def unknown_p14_owner(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                ET.SubElement(
                    document,
                    f"{{{p14_namespace}}}creationId",
                    {"val": "123456"},
                )
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            unknown_p14 = root / "unknown-p14-owner.pptx"
            mutate_zip_member(
                source,
                unknown_p14,
                "docProps/core.xml",
                unknown_p14_owner,
            )
            with self.assertRaisesRegex(VerificationError, "p14 creationId位于未知上下文或计数异常"):
                normalize_pptx(unknown_p14)

    def test_default_pptx_missing_dependency_and_dual_failure_commit_nothing(self):
        for formats in ([], ["--format", "pptx", "--format", "html"]):
            with self.subTest(formats=formats), tempfile.TemporaryDirectory() as raw:
                out = Path(raw) / "bundle"
                env = {**os.environ, "S2_PPTX_FORCE_UNAVAILABLE": "1"}
                command = [
                    sys.executable,
                    str(RUNNER),
                    "--enable-client-delivery",
                    "--case-id",
                    "SAMPLE-01",
                    "--frozen07-dir",
                    str(FIXTURE),
                    "--text-pass-receipt",
                    str(FIXTURE / "TEXT-PASS-RECEIPT.json"),
                    "--delivery-profile",
                    str(FIXTURE / "CLIENT-DELIVERY-PROFILE.json"),
                    "--out",
                    str(out),
                    "--run-id",
                    "S2-TEST-HOLD",
                    *formats,
                ]
                result = subprocess.run(command, capture_output=True, text=True, env={**env, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=30)
                self.assertEqual(3, result.returncode)
                self.assertFalse(out.exists())
                receipts = list(Path(raw).glob(f".{out.name}.S2-TEST-HOLD.*.failure.json"))
                self.assertEqual(1, len(receipts))
                failure = json.loads(receipts[0].read_text(encoding="utf-8"))
                self.assertTrue(failure["formal_output_unchanged"])
                self.assertEqual([], failure["produced_committed"])

    def test_failure_receipt_is_separate_private_and_does_not_commit_partial_output(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            out = root / "bundle"
            receipt = root / "bundle.failure.json"
            env = {**os.environ, "S2_PPTX_FORCE_UNAVAILABLE": "1"}
            command = [
                sys.executable,
                str(RUNNER),
                "--enable-client-delivery",
                "--case-id",
                "SAMPLE-01",
                "--frozen07-dir",
                str(FIXTURE),
                "--text-pass-receipt",
                str(FIXTURE / "TEXT-PASS-RECEIPT.json"),
                "--delivery-profile",
                str(FIXTURE / "CLIENT-DELIVERY-PROFILE.json"),
                "--out",
                str(out),
                "--run-id",
                "S2-TEST-FAILURE-RECEIPT",
                "--failure-receipt",
                str(receipt),
            ]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                env={**env, "PYTHONDONTWRITEBYTECODE": "1"},
                timeout=30,
            )
            self.assertEqual(3, result.returncode)
            self.assertFalse(out.exists())
            self.assertTrue(receipt.is_file())
            failure = json.loads(receipt.read_text(encoding="utf-8"))
            schema = json.loads(
                (CANDIDATE / "references" / "contracts" / "failure-receipt-v2.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual([], list(Draft202012Validator(schema).iter_errors(failure)))
            self.assertEqual("ENGINE_UNAVAILABLE", failure["failures"][0]["failure_code"])
            self.assertTrue(failure["staging_deleted"])
            self.assertTrue(failure["formal_output_unchanged"])
            self.assertEqual([], failure["produced_committed"])
            self.assertNotIn(str(FIXTURE), receipt.read_text(encoding="utf-8"))

            overwrite = subprocess.run(
                command,
                capture_output=True,
                text=True,
                env={**env, "PYTHONDONTWRITEBYTECODE": "1"},
                timeout=30,
            )
            self.assertEqual(3, overwrite.returncode)
            self.assertIn("不得覆盖现有路径", overwrite.stderr)

    def test_pptx_rejects_external_relationship_and_picture(self):
        ir = build_delivery_ir(sample_inputs(), PACKAGE)
        with tempfile.TemporaryDirectory() as raw:
            pptx = Path(raw) / "bad.pptx"
            with zipfile.ZipFile(pptx, "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types/>")
                archive.writestr(
                    "ppt/presentation.xml",
                    '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>',
                )
                archive.writestr(
                    "ppt/_rels/presentation.xml.rels",
                    '<Relationships><Relationship TargetMode="External" Target="https://invalid"/></Relationships>',
                )
                archive.writestr(
                    "ppt/slides/slide1.xml",
                    '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:pic/></p:sld>',
                )
            with self.assertRaises(VerificationError):
                verify_pptx(pptx, ir)

    @unittest.skipUnless(PYTHON_PPTX_AVAILABLE, "python-pptx runtime not configured")
    def test_pptx_semantic_inventory_and_cjk_font_checks_are_discriminating(self):
        ir = build_delivery_ir(sample_inputs(), PACKAGE)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            out = root / "valid"
            result = self.run_candidate(out, "S2-TEST-SEMANTIC-PPTX")
            self.assertEqual(0, result.returncode, result.stderr)
            source = out / "client-briefing.REVIEW-DRAFT.pptx"
            receipt = verify_pptx(source, ir)
            self.assertEqual("complete", receipt["semantic_completeness"]["status"])
            self.assertEqual("complete", receipt["visible_object_ledger"]["status"])
            self.assertEqual(0, receipt["visible_object_ledger"]["extra_object_count"])
            self.assertEqual(
                0, receipt["visible_object_ledger"]["rewritten_text_object_count"]
            )
            self.assertEqual("pass", receipt["openxml_schema_order"]["status"])
            self.assertGreater(
                receipt["openxml_schema_order"]["run_properties_checked"], 0
            )
            self.assertGreater(
                receipt["openxml_schema_order"]["table_cell_properties_checked"], 0
            )
            self.assertEqual(
                {
                    "all_package_parts",
                    "slide_text",
                    "shape_names_and_alt_text",
                    "speaker_notes",
                    "document_properties",
                    "relationships",
                },
                set(receipt["privacy_scan"]["scopes"]),
            )
            typography = receipt["text_typography"]
            self.assertEqual("final_ooxml_a:rPr_sz", typography["authority"])
            self.assertEqual(
                {
                    "AUX": 9.0,
                    "BODY": 16.5,
                    "DECK": 50.25,
                    "MID": 24.0,
                    "SLIDE": 35.25,
                },
                typography["minimum_actual_points"],
            )
            self.assertTrue(
                all(typography["role_counts"].get(role, 0) > 0 for role in ("AUX", "BODY", "DECK", "MID", "SLIDE"))
            )

            with zipfile.ZipFile(source) as archive:
                slide_payloads = [
                    archive.read(name)
                    for name in sorted(
                        value
                        for value in archive.namelist()
                        if re.fullmatch(r"ppt/slides/slide\d+\.xml", value)
                    )
                ]
                visible_slide_text = "".join(
                    node.text or ""
                    for payload in slide_payloads
                    for node in ET.fromstring(payload).findall(
                        ".//a:t",
                        {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"},
                    )
                )
                self.assertIn("审阅稿", visible_slide_text)
                self.assertIn("诉讼可视化简报", visible_slide_text)
                self.assertIn("仅供内部审阅", visible_slide_text)
                fixed_chrome_text: dict[str, str] = {}
                for payload in slide_payloads:
                    document = ET.fromstring(payload)
                    for shape in document.findall(".//p:sp", {
                        "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
                    }):
                        properties = shape.find(
                            "./p:nvSpPr/p:cNvPr",
                            {"p": "http://schemas.openxmlformats.org/presentationml/2006/main"},
                        )
                        name = properties.attrib.get("name", "") if properties is not None else ""
                        base = name.split("|", 1)[0]
                        if base.endswith((
                            ":series",
                            ":draft",
                            ":eyebrow",
                            ":release-state",
                            ":boundary-panel",
                            ":no-release",
                        )):
                            fixed_chrome_text[base] = "".join(
                                node.text or "" for node in shape.findall(".//a:t", {
                                    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
                                })
                            )
                self.assertEqual("诉讼可视化简报", fixed_chrome_text["cover-01:series"])
                self.assertEqual("审阅稿仅供内部审阅", fixed_chrome_text["cover-01:draft"])
                self.assertTrue(
                    all(
                        value == "诉讼可视化简报 · 客户审阅材料"
                        for key, value in fixed_chrome_text.items()
                        if key.endswith(":eyebrow")
                    )
                )
                self.assertTrue(
                    all(
                        value == "审阅稿"
                        for key, value in fixed_chrome_text.items()
                        if key.endswith(":release-state")
                    )
                )
                for legacy_label in (
                    "LITIGATION BRIEF",
                    "CLIENT DELIVERY",
                    "REVIEW DRAFT",
                    "INTERNAL_REVIEW_ONLY",
                    "ATTORNEY_WORK_PRODUCT",
                    "CLIENT-READY",
                ):
                    self.assertTrue(
                        all(legacy_label not in value for value in fixed_chrome_text.values()),
                        legacy_label,
                    )
                core_xml = archive.read("docProps/core.xml").decode("utf-8")
                self.assertIn("诉讼可视化简报（审阅稿）", core_xml)
                self.assertIn("诉讼可视化交付工具", core_xml)
                self.assertNotIn("Sublation Client Delivery", core_xml)
                app_xml = archive.read("docProps/app.xml").decode("utf-8")
                self.assertIn("诉讼可视化交付工具", app_xml)
                self.assertNotIn("Sublation Client Delivery", app_xml)
                notes_xml = "".join(
                    archive.read(name).decode("utf-8")
                    for name in sorted(archive.namelist())
                    if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", name)
                )
                self.assertIn("审阅稿；未自动取得客户放行。", notes_xml)
                self.assertNotIn("REVIEW DRAFT; no automatic client release.", notes_xml)
                self.assertIn("【来源】", notes_xml)
                self.assertNotIn("[Sources]", notes_xml)
                self.assertNotIn("[Boundary]", notes_xml)
                # Notes pages are customer-visible in presenter/print views, so
                # every notes run carries the same zh-CN + delivery-font marks.
                notes_names = sorted(
                    name
                    for name in archive.namelist()
                    if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", name)
                )
                self.assertEqual(len(ir["slides"]), len(notes_names))
                for name in notes_names:
                    document = ET.fromstring(archive.read(name))
                    runs = document.findall(".//a:r", NS_A)
                    run_properties = document.findall(".//a:rPr", NS_A)
                    self.assertTrue(runs)
                    self.assertEqual(len(runs), len(run_properties))
                    for properties in run_properties:
                        self.assertEqual("zh-CN", properties.attrib.get("lang"))
                        for font_tag in ("a:latin", "a:ea", "a:cs"):
                            font = properties.find(font_tag, NS_A)
                            self.assertIsNotNone(font)
                            self.assertEqual("Microsoft YaHei", font.attrib.get("typeface"))
                # docProps must not leak the python-pptx template's English
                # chrome (PresentationFormat / HeadingPairs / TitlesOfParts).
                self.assertIn("宽屏 (16:9)", app_xml)
                self.assertNotIn("On-screen Show", app_xml)
                self.assertNotIn("Office Theme", app_xml)
                self.assertNotIn("Slide Titles", app_xml)
                self.assertIn("诉讼可视化主题", app_xml)
                for payload in slide_payloads:
                    document = ET.fromstring(payload)
                    for properties in document.findall(".//a:rPr", {
                        "a": "http://schemas.openxmlformats.org/drawingml/2006/main"
                    }):
                        self.assertEqual("zh-CN", properties.attrib.get("lang"))
                        for font_tag in ("a:latin", "a:ea", "a:cs"):
                            font = properties.find(font_tag, {
                                "a": "http://schemas.openxmlformats.org/drawingml/2006/main"
                            })
                            self.assertIsNotNone(font)
                            self.assertEqual("Microsoft YaHei", font.attrib.get("typeface"))

            ns = {
                "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
                "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
            }

            def mutate_visible_run_size(prefix: str, size: int, *, table: bool = False):
                def mutate(payload: bytes) -> bytes:
                    document = ET.fromstring(payload)
                    container_path, properties_path = (
                        (".//p:graphicFrame", "./p:nvGraphicFramePr/p:cNvPr")
                        if table
                        else (".//p:sp", "./p:nvSpPr/p:cNvPr")
                    )
                    containers = []
                    for container in document.findall(container_path, ns):
                        properties = container.find(properties_path, ns)
                        name = properties.attrib.get("name", "") if properties is not None else ""
                        if name == prefix or name.startswith(prefix + "|"):
                            containers.append(container)
                    self.assertEqual(1, len(containers), prefix)
                    changed = 0
                    for run in containers[0].findall(".//a:r", ns):
                        if not "".join(node.text or "" for node in run.findall(".//a:t", ns)).strip():
                            continue
                        run_properties = run.find("a:rPr", ns)
                        self.assertIsNotNone(run_properties)
                        run_properties.attrib["sz"] = str(size)
                        changed += 1
                        if table:
                            break
                    self.assertGreater(changed, 0)
                    return ET.tostring(document, encoding="utf-8", xml_declaration=True)

                return mutate

            def remove_deck_role(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                changed = 0
                for properties in document.findall(".//p:sp/p:nvSpPr/p:cNvPr", ns):
                    name = properties.attrib.get("name", "")
                    if name.startswith("cover-01:matter|"):
                        properties.attrib["name"] = name.replace("|TEXTROLE|DECK|", "", 1)
                        changed += 1
                self.assertEqual(1, changed)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            first_slide = "ppt/slides/slide1.xml"
            noncover_slide = ir["slides"][1]
            noncover_member = "ppt/slides/slide2.xml"
            evidence_index = next(
                index
                for index, slide_item in enumerate(ir["slides"])
                if slide_item["role"] == "evidence_matrix" and slide_item["content"]["rows"]
            )
            evidence_slide = ir["slides"][evidence_index]

            def misorder_run_fonts(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                changed = 0
                for properties in document.findall(".//a:rPr", ns):
                    east_asian = properties.find("a:ea", ns)
                    latin = properties.find("a:latin", ns)
                    if east_asian is None or latin is None:
                        continue
                    properties.remove(east_asian)
                    properties.insert(0, east_asian)
                    changed += 1
                    break
                self.assertEqual(1, changed)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def misorder_table_border(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                changed = 0
                for properties in document.findall(".//a:tcPr", ns):
                    left = properties.find("a:lnL", ns)
                    fill = properties.find("a:solidFill", ns)
                    if left is None or fill is None:
                        continue
                    properties.remove(left)
                    properties.append(left)
                    changed += 1
                    break
                self.assertEqual(1, changed)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def replace_delivery_font(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                changed = 0
                for properties in document.findall(".//a:rPr", ns):
                    for font_tag in ("a:latin", "a:ea", "a:cs"):
                        font = properties.find(font_tag, ns)
                        if font is not None:
                            font.attrib["typeface"] = "Arial"
                            changed += 1
                    if changed:
                        break
                self.assertEqual(3, changed)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def remove_zh_cn_language(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                properties = document.find(".//a:rPr", ns)
                self.assertIsNotNone(properties)
                self.assertEqual("zh-CN", properties.attrib.pop("lang", None))
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def enable_fixed_chrome_wrap(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                changed = 0
                for shape in document.findall(".//p:sp", ns):
                    properties = shape.find("./p:nvSpPr/p:cNvPr", ns)
                    name = properties.attrib.get("name", "") if properties is not None else ""
                    if not name.startswith(f"{noncover_slide['slide_id']}:release-state|"):
                        continue
                    body = shape.find("./p:txBody/a:bodyPr", ns)
                    self.assertIsNotNone(body)
                    body.attrib["wrap"] = "square"
                    changed += 1
                self.assertEqual(1, changed)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def restore_legacy_review_label(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                changed = 0
                for shape in document.findall(".//p:sp", ns):
                    properties = shape.find("./p:nvSpPr/p:cNvPr", ns)
                    name = properties.attrib.get("name", "") if properties is not None else ""
                    if not name.startswith(f"{noncover_slide['slide_id']}:release-state|"):
                        continue
                    text_node = shape.find(".//a:t", ns)
                    self.assertIsNotNone(text_node)
                    text_node.text = "REVIEW DRAFT"
                    changed += 1
                self.assertEqual(1, changed)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            for name, member, mutation in (
                ("misordered-run-fonts", first_slide, misorder_run_fonts),
                (
                    "misordered-table-border",
                    f"ppt/slides/slide{evidence_index + 1}.xml",
                    misorder_table_border,
                ),
            ):
                bad_order = root / f"{name}.pptx"
                mutate_zip_member(source, bad_order, member, mutation)
                with self.subTest(name=name), self.assertRaisesRegex(
                    VerificationError, "PPTX_OPENXML_CHILD_ORDER_INVALID"
                ):
                    verify_pptx(bad_order, ir)

            def restore_english_notes_heading(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                changed = 0
                for node in document.findall(".//a:t", NS_A):
                    if node.text == "【来源】":
                        node.text = "[Sources]"
                        changed += 1
                self.assertEqual(1, changed)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def strip_notes_run_fonts(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                properties = document.find(".//a:rPr", NS_A)
                self.assertIsNotNone(properties)
                self.assertEqual("zh-CN", properties.attrib.pop("lang", None))
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def add_bare_notes_run_with_compliant_fld(payload: bytes) -> bytes:
                # An a:fld may legitimately carry its own compliant a:rPr, so an
                # aggregate rPr-vs-run count would let this bare run ride along.
                document = ET.fromstring(payload)
                paragraph = document.find(".//a:p", NS_A)
                self.assertIsNotNone(paragraph)
                # Empty text so the paragraph compare still matches: this must
                # be caught by the per-run font/lang check, nothing else.
                bare = ET.SubElement(paragraph, "{%s}r" % NS_A["a"])
                ET.SubElement(bare, "{%s}t" % NS_A["a"]).text = ""
                field = ET.SubElement(paragraph, "{%s}fld" % NS_A["a"])
                field.set("id", "{00000000-0000-0000-0000-000000000001}")
                field.set("type", "slidenum")
                field_properties = ET.SubElement(field, "{%s}rPr" % NS_A["a"])
                field_properties.set("lang", "zh-CN")
                for font_tag in ("latin", "ea", "cs"):
                    ET.SubElement(
                        field_properties, "{%s}%s" % (NS_A["a"], font_tag)
                    ).set("typeface", "Microsoft YaHei")
                ET.SubElement(field, "{%s}t" % NS_A["a"]).text = "1"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def orphan_notes_part(payload: bytes) -> bytes:
                # Drop slide 1's notes relationship, leaving notesSlide1 orphaned.
                document = ET.fromstring(payload)
                notes_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide"
                removed = 0
                for node in list(document):
                    if node.attrib.get("Type") == notes_type:
                        document.remove(node)
                        removed += 1
                self.assertEqual(1, removed)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def collapse_notes_paragraphs(payload: bytes) -> bytes:
                # Flatten every line into one paragraph: a concatenated-text
                # compare cannot see this, a per-paragraph compare must.
                document = ET.fromstring(payload)
                body = document.find(".//p:txBody", {
                    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
                })
                paragraphs = [] if body is None else body.findall("a:p", NS_A)
                self.assertGreater(len(paragraphs), 1)
                keeper = paragraphs[0]
                for extra in paragraphs[1:]:
                    for run in extra.findall("a:r", NS_A):
                        keeper.append(run)
                    body.remove(extra)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def restore_english_presentation_format(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                node = document.find(
                    "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}PresentationFormat"
                )
                self.assertIsNotNone(node)
                node.text = "On-screen Show (4:3)"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def restore_english_theme_label(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                changed = 0
                for node in document.iter(
                    "{http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes}lpstr"
                ):
                    if node.text == "诉讼可视化主题":
                        node.text = "Office Theme"
                        changed += 1
                self.assertEqual(1, changed)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def restore_english_core_title(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                node = document.find("dc:title", CORE_NS_TEST)
                self.assertIsNotNone(node)
                node.text = "Litigation Brief - Review Draft"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            fixed_chrome_mutations = (
                ("wrong-delivery-font", first_slide, replace_delivery_font, "PPTX_TEXT_FONT_INVALID"),
                ("missing-zh-cn-language", first_slide, remove_zh_cn_language, "PPTX_TEXT_LANGUAGE_INVALID"),
                ("fixed-chrome-wrap", noncover_member, enable_fixed_chrome_wrap, "PPTX_FIXED_CHROME_INVALID"),
                ("legacy-review-label", noncover_member, restore_legacy_review_label, "PPTX_VISIBLE_OBJECT_LEDGER_INVALID"),
                ("english-notes-heading", "ppt/notesSlides/notesSlide1.xml", restore_english_notes_heading, "PPTX_NOTES_INVALID"),
                ("notes-missing-zh-cn", "ppt/notesSlides/notesSlide1.xml", strip_notes_run_fonts, "PPTX_NOTES_INVALID"),
                ("notes-bare-run-plus-fld", "ppt/notesSlides/notesSlide1.xml", add_bare_notes_run_with_compliant_fld, "PPTX_NOTES_INVALID"),
                ("notes-paragraphs-collapsed", "ppt/notesSlides/notesSlide3.xml", collapse_notes_paragraphs, "PPTX_NOTES_INVALID"),
                ("notes-orphaned-part", "ppt/slides/_rels/slide1.xml.rels", orphan_notes_part, "PPTX_NOTES_INVALID"),
                ("english-presentation-format", "docProps/app.xml", restore_english_presentation_format, "PPTX_DOC_PROPERTIES_INVALID"),
                ("english-theme-label", "docProps/app.xml", restore_english_theme_label, "PPTX_DOC_PROPERTIES_INVALID"),
                ("english-core-title", "docProps/core.xml", restore_english_core_title, "PPTX_DOC_PROPERTIES_INVALID"),
            )
            for name, member, mutation, message in fixed_chrome_mutations:
                bad_fixed_chrome = root / f"{name}.pptx"
                mutate_zip_member(source, bad_fixed_chrome, member, mutation)
                with self.subTest(name=name), self.assertRaisesRegex(
                    VerificationError, message
                ):
                    verify_pptx(bad_fixed_chrome, ir)

            typography_mutations = (
                ("deck-49_9", first_slide, mutate_visible_run_size("cover-01:matter", 4990), r"DECK.*actual=49.90pt.*required=50.00pt"),
                ("slide-34_9", noncover_member, mutate_visible_run_size(f'{noncover_slide["slide_id"]}:title', 3490), r"SLIDE.*actual=34.90pt.*required=35.00pt"),
                ("body-15_9", first_slide, mutate_visible_run_size("cover-01:meta", 1590), r"BODY.*actual=15.90pt.*required=16.00pt"),
                ("legacy-artifact16-is-ooxml12", first_slide, mutate_visible_run_size("cover-01:meta", 1200), r"BODY.*actual=12.00pt.*required=16.00pt"),
                ("missing-text-role", first_slide, remove_deck_role, r"PPTX_TEXT_ROLE_INVALID"),
                (
                    "table-cell-15_9",
                    f"ppt/slides/slide{evidence_index + 1}.xml",
                    mutate_visible_run_size(f'{evidence_slide["slide_id"]}:matrix', 1590, table=True),
                    r"BODY.*actual=15.90pt.*required=16.00pt",
                ),
            )
            for name, member, mutation, message in typography_mutations:
                bad_typography = root / f"{name}.pptx"
                mutate_zip_member(source, bad_typography, member, mutation)
                with self.subTest(name=name), self.assertRaisesRegex(
                    VerificationError, message
                ):
                    verify_pptx(bad_typography, ir)

            def append_inside_existing_semantic_text(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                changed = 0
                for shape in document.findall(".//p:sp", ns):
                    properties = shape.find("./p:nvSpPr/p:cNvPr", ns)
                    name = properties.attrib.get("name", "") if properties is not None else ""
                    if not name.startswith("cover-01:matter|"):
                        continue
                    text_node = shape.find(".//a:t", ns)
                    self.assertIsNotNone(text_node)
                    text_node.text = (text_node.text or "") + "SEMANTIC-INNER-PPTX-SENTINEL"
                    changed += 1
                self.assertEqual(1, changed)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def inject_extra_text_shape(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                tree = document.find("./p:cSld/p:spTree", ns)
                self.assertIsNotNone(tree)
                source_shape = next(
                    shape
                    for shape in document.findall(".//p:sp", ns)
                    if shape.find(".//a:t", ns) is not None
                )
                injected = copy.deepcopy(source_shape)
                properties = injected.find("./p:nvSpPr/p:cNvPr", ns)
                self.assertIsNotNone(properties)
                properties.attrib["id"] = "900001"
                properties.attrib["name"] = (
                    "UNREGISTERED-PPTX-TEXTBOX|TEXTROLE|AUX|"
                )
                for text_node in injected.findall(".//a:t", ns):
                    text_node.text = "UNREGISTERED-PPTX-VISIBLE-TEXT"
                tree.append(injected)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def inject_extra_nontext_shape(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                tree = document.find("./p:cSld/p:spTree", ns)
                self.assertIsNotNone(tree)
                source_shape = None
                for shape in document.findall(".//p:sp", ns):
                    properties = shape.find("./p:nvSpPr/p:cNvPr", ns)
                    name = properties.attrib.get("name", "") if properties is not None else ""
                    if name.startswith(f'{noncover_slide["slide_id"]}:header-rule'):
                        source_shape = shape
                        break
                self.assertIsNotNone(source_shape)
                injected = copy.deepcopy(source_shape)
                properties = injected.find("./p:nvSpPr/p:cNvPr", ns)
                self.assertIsNotNone(properties)
                properties.attrib["id"] = "900002"
                properties.attrib["name"] = "UNREGISTERED-PPTX-SHAPE"
                tree.append(injected)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            for name, member, mutation in (
                (
                    "semantic-inner-visible-text",
                    first_slide,
                    append_inside_existing_semantic_text,
                ),
                ("extra-visible-text-shape", first_slide, inject_extra_text_shape),
                ("extra-nontext-shape", noncover_member, inject_extra_nontext_shape),
            ):
                bad_object = root / f"{name}.pptx"
                mutate_zip_member(source, bad_object, member, mutation)
                with self.subTest(name=name), self.assertRaisesRegex(
                    VerificationError, "PPTX_VISIBLE_OBJECT_LEDGER_INVALID"
                ):
                    verify_pptx(bad_object, ir)

            with zipfile.ZipFile(source) as archive:
                slide = archive.read("ppt/slides/slide1.xml")
            ids = re.findall(rb"\|SEMITEM\|(sem:[A-Za-z0-9._:-]+)\|", slide)
            self.assertGreaterEqual(len(ids), 5)

            def missing(payload: bytes) -> bytes:
                token = b"|SEMITEM|" + ids[0] + b"|"
                return payload.replace(token, b"", 1)

            def duplicate(payload: bytes) -> bytes:
                return payload.replace(ids[1], ids[0], 1)

            def reordered(payload: bytes) -> bytes:
                return payload.replace(ids[0], b"SEMANTIC_SWAP_TEMP", 1).replace(
                    ids[1], ids[0], 1
                ).replace(b"SEMANTIC_SWAP_TEMP", ids[1], 1)

            for name, mutate in {
                "missing": missing,
                "duplicate": duplicate,
                "reordered": reordered,
            }.items():
                bad = root / f"{name}.pptx"
                mutate_zip_member(source, bad, "ppt/slides/slide1.xml", mutate)
                with self.subTest(name=name), self.assertRaisesRegex(
                    VerificationError, "SILENT_TRUNCATION_DETECTED"
                ):
                    verify_pptx(bad, ir)

            def remove_east_asian_font(payload: bytes) -> bytes:
                ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
                root = ET.fromstring(payload)
                removed = False
                for paragraph in root.findall(".//a:p", ns):
                    text = "".join(node.text or "" for node in paragraph.findall(".//a:t", ns))
                    if not re.search(r"[\u3400-\u9fff]", text):
                        continue
                    for properties in paragraph.findall(".//a:rPr", ns):
                        east_asian = properties.find("a:ea", ns)
                        if east_asian is not None:
                            properties.remove(east_asian)
                            removed = True
                            break
                    if removed:
                        break
                self.assertTrue(removed)
                return ET.tostring(root, encoding="utf-8", xml_declaration=True)

            missing_font = root / "missing-font.pptx"
            mutate_zip_member(
                source,
                missing_font,
                "ppt/slides/slide1.xml",
                remove_east_asian_font,
            )
            with self.assertRaisesRegex(VerificationError, "PPTX_TEXT_FONT_INVALID"):
                verify_pptx(missing_font, ir)

            def inject_marker(payload: bytes) -> bytes:
                return payload + b"PII_CANARY"

            def inject_path(marker: bytes):
                def mutate(payload: bytes) -> bytes:
                    return payload + marker

                return mutate

            def inject_alt_text(payload: bytes) -> bytes:
                changed, count = re.subn(
                    rb"(<p:cNvPr\b)", rb'\1 descr="PII_CANARY"', payload, count=1
                )
                self.assertEqual(1, count)
                return changed

            with zipfile.ZipFile(source) as archive:
                names = set(archive.namelist())
            note_member = next(
                name
                for name in sorted(names)
                if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", name)
            )
            for name, member, mutation in (
                ("notes-privacy", note_member, inject_marker),
                ("docprops-privacy", "docProps/core.xml", inject_marker),
                ("alt-text-privacy", "ppt/slides/slide1.xml", inject_alt_text),
                (
                    "macos-user-directory-privacy",
                    note_member,
                    inject_path(b"/Users/LOCAL_ACCOUNT_CANARY/Documents/private.txt"),
                ),
                (
                    "linux-user-directory-privacy",
                    note_member,
                    inject_path(b"/home/LOCAL_ACCOUNT_CANARY/private.txt"),
                ),
                (
                    "windows-user-directory-privacy",
                    note_member,
                    inject_path(
                        b"C:\\Users\\LOCAL_ACCOUNT_CANARY\\Documents\\private.txt"
                    ),
                ),
            ):
                bad_privacy = root / f"{name}.pptx"
                mutate_zip_member(source, bad_privacy, member, mutation)
                with self.subTest(name=name), self.assertRaisesRegex(
                    VerificationError, "隐私扫描"
                ):
                    verify_pptx(bad_privacy, ir)

            def zero_slide_count(payload: bytes) -> bytes:
                root = ET.fromstring(payload)
                node = root.find(
                    "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}Slides"
                )
                self.assertIsNotNone(node)
                node.text = "0"
                return ET.tostring(root, encoding="utf-8", xml_declaration=True)

            bad_app = root / "bad-app-count.pptx"
            mutate_zip_member(source, bad_app, "docProps/app.xml", zero_slide_count)
            with self.assertRaisesRegex(VerificationError, "Slides/Notes计数不准确"):
                verify_pptx(bad_app, ir)

    @unittest.skipUnless(PYTHON_PPTX_AVAILABLE, "python-pptx runtime not configured")
    def test_r3_pptx_metadata_theme_and_editable_template_gates_are_discriminating(self):
        """Self-consistent OOXML drift must fail independently of rendering.

        These controls deliberately mutate fields that the R2 verifier did not
        bind: arbitrary-but-valid document-property labels, theme display/font
        defaults, the editable layout/master/notes-master surfaces, and the R4
        slide-size type/dimensions carried by presentation.xml.
        """

        ir = build_delivery_ir(sample_inputs(), PACKAGE)
        unknown_confidentiality = copy.deepcopy(ir)
        unknown_confidentiality["profile"]["confidentiality"] = "UNMAPPED"
        with self.assertRaisesRegex(
            VerificationError, "confidentiality缺少简体中文显示映射"
        ):
            _expected_pptx_objects(
                unknown_confidentiality,
                unknown_confidentiality["slides"][0],
                0,
            )

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            out = root / "valid"
            result = self.run_candidate(
                out, "S2-TEST-R3-EDITABLE-TEMPLATE", formats=["pptx"]
            )
            self.assertEqual(0, result.returncode, result.stderr)
            source = out / "client-briefing.REVIEW-DRAFT.pptx"

            p_ns = {
                "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
                "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
            }
            app_ns = (
                "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
            )

            writer_ir = root / "writer-delivery-ir.json"
            writer_ir.write_text(
                json.dumps(ir, ensure_ascii=False, sort_keys=True), encoding="utf-8"
            )
            writer_output = root / "writer-direct.pptx"
            writer_qa = root / "writer-direct-qa"
            writer_result = subprocess.run(
                [
                    sys.executable,
                    str(PPTX_WRITER),
                    "--input",
                    str(writer_ir),
                    "--output",
                    str(writer_output),
                    "--qa",
                    str(writer_qa),
                ],
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                timeout=240,
            )
            self.assertEqual(0, writer_result.returncode, writer_result.stderr)
            with self.subTest(label="writer-emits-exact-screen16x9"):
                with zipfile.ZipFile(writer_output) as archive:
                    document = ET.fromstring(archive.read("ppt/presentation.xml"))
                nodes = document.findall("./p:sldSz", p_ns)
                self.assertEqual(1, len(nodes))
                self.assertEqual(
                    {"cx": "12192000", "cy": "6858000", "type": "screen16x9"},
                    nodes[0].attrib,
                )
            with self.subTest(label="writer-emits-closed-default-text-style"):
                default_style = document.find("./p:defaultTextStyle", p_ns)
                self.assertIsNotNone(default_style)
                self.assertEqual({}, default_style.attrib)
                self.assertEqual(
                    ["defPPr", *[f"lvl{level}pPr" for level in range(1, 10)]],
                    [child.tag.rsplit("}", 1)[-1] for child in list(default_style)],
                )
                default_paragraph = default_style.find("./a:defPPr", p_ns)
                self.assertIsNotNone(default_paragraph)
                self.assertEqual({}, default_paragraph.attrib)
                self.assertEqual(
                    ["defRPr"],
                    [child.tag.rsplit("}", 1)[-1] for child in default_paragraph],
                )
                self.assertEqual(
                    {"lang": "zh-CN"},
                    default_paragraph.find("./a:defRPr", p_ns).attrib,
                )
                default_runs = default_style.findall(".//a:defRPr", p_ns)
                self.assertEqual(10, len(default_runs))
                self.assertTrue(
                    all(run.attrib.get("lang") == "zh-CN" for run in default_runs)
                )
                for level in range(1, 10):
                    level_node = default_style.find(f"./a:lvl{level}pPr", p_ns)
                    self.assertIsNotNone(level_node)
                    run = level_node.find("./a:defRPr", p_ns)
                    self.assertIsNotNone(run)
                    self.assertEqual(
                        {
                            "marL": str((level - 1) * 457200),
                            "algn": "l",
                            "defTabSz": "457200",
                            "rtl": "0",
                            "eaLnBrk": "1",
                            "latinLnBrk": "0",
                            "hangingPunct": "1",
                        },
                        level_node.attrib,
                    )
                    self.assertEqual(
                        {"sz": "1800", "kern": "1200", "lang": "zh-CN"},
                        run.attrib,
                    )
                    self.assertEqual(
                        ["solidFill", "latin", "ea", "cs"],
                        [child.tag.rsplit("}", 1)[-1] for child in list(run)],
                    )
                    solid_fill = run.find("./a:solidFill", p_ns)
                    self.assertEqual({}, solid_fill.attrib)
                    scheme_color = solid_fill.find("./a:schemeClr", p_ns)
                    self.assertEqual({"val": "tx1"}, scheme_color.attrib)
                    fonts = [
                        child
                        for child in list(run)
                        if child.tag.rsplit("}", 1)[-1] in {"latin", "ea", "cs"}
                    ]
                    self.assertEqual(["latin", "ea", "cs"], [
                        child.tag.rsplit("}", 1)[-1] for child in fonts
                    ])
                    self.assertEqual(
                        [{"typeface": "Microsoft YaHei"}] * 3,
                        [child.attrib for child in fonts],
                    )

            from pptx import Presentation
            from pptx.oxml.ns import qn
            from pptx.oxml.xmlchemy import OxmlElement

            for label, mutate_writer_template in (
                (
                    "writer-rejects-default-font-extra-attribute",
                    lambda node: node.set("unregistered", "drift"),
                ),
                (
                    "writer-rejects-default-font-extra-child",
                    lambda node: node.append(OxmlElement("a:ext")),
                ),
            ):
                template = Presentation()
                font = template._element.find(
                    ".//" + qn("a:lvl1pPr") + "/" + qn("a:defRPr") + "/" + qn("a:latin")
                )
                self.assertIsNotNone(font)
                mutate_writer_template(font)
                with self.subTest(label=label), self.assertRaisesRegex(
                    ValueError, "defaultTextStyle level 1 a:latin drifted"
                ):
                    _close_presentation_default_text_style(template)

            def unmapped_app_label(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                node = next(document.iter(f"{{{app_ns}}}lpstr"))
                node.text = "任意未登记标签"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def unmapped_titles_label(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                titles = document.find(
                    "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}TitlesOfParts"
                )
                self.assertIsNotNone(titles)
                node = next(titles.iter(f"{{{app_ns}}}lpstr"))
                node.text = "任意未登记主题标签"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def drift_unmapped_app_field(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                node = document.find(
                    "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}TotalTime"
                )
                self.assertIsNotNone(node)
                node.text = "2"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def drift_unmapped_core_field(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                node = document.find(
                    "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}keywords"
                )
                self.assertIsNotNone(node)
                node.text = "任意未登记关键词"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def arbitrary_theme_name(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                document.attrib["name"] = "任意未登记主题"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def legacy_theme_font(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                node = document.find(".//a:latin", p_ns)
                self.assertIsNotNone(node)
                node.attrib["typeface"] = "Calibri"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def delete_theme_font_node(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                target = document.find(".//a:fontScheme/a:majorFont/a:latin", p_ns)
                self.assertIsNotNone(target)
                parent = next(item for item in document.iter() if target in list(item))
                parent.remove(target)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def arbitrary_theme_scheme(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                node = document.find(".//a:clrScheme", p_ns)
                self.assertIsNotNone(node)
                node.attrib["name"] = "任意未登记配色"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def arbitrary_template_text(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                node = document.find(".//a:t", p_ns)
                self.assertIsNotNone(node)
                node.text = "任意未登记母版提示"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def substitute_allowed_template_text(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                node = document.find(".//a:t", p_ns)
                self.assertIsNotNone(node)
                node.text = "第二级"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def delete_template_text(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                target = document.find(".//a:t", p_ns)
                self.assertIsNotNone(target)
                parent = next(item for item in document.iter() if target in list(item))
                parent.remove(target)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def arbitrary_template_name(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                node = next(
                    item
                    for item in document.findall(".//p:cNvPr", p_ns)
                    if item.attrib.get("name")
                )
                node.attrib["name"] = "任意未登记占位符"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def substitute_allowed_template_name(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                node = next(
                    item
                    for item in document.findall(".//p:cNvPr", p_ns)
                    if item.attrib.get("name")
                )
                node.attrib["name"] = "副标题 1"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def substitute_allowed_layout_name(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                node = document.find("./p:cSld", p_ns)
                self.assertIsNotNone(node)
                node.attrib["name"] = "空白"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def legacy_template_language(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                node = next(
                    item
                    for tag in ("a:rPr", "a:defRPr", "a:endParaRPr")
                    for item in document.findall(f".//{tag}", p_ns)
                )
                node.attrib["lang"] = "en-US"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def legacy_template_font(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                node = next(
                    item
                    for tag in ("a:latin", "a:ea", "a:cs", "a:buFont")
                    for item in document.findall(f".//{tag}", p_ns)
                )
                node.attrib["typeface"] = "Arial"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def screen4x3_slide_size(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                node = document.find("./p:sldSz", p_ns)
                self.assertIsNotNone(node)
                node.attrib["type"] = "screen4x3"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def missing_slide_size_type(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                node = document.find("./p:sldSz", p_ns)
                self.assertIsNotNone(node)
                node.attrib.pop("type", None)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def wrong_slide_size_dimensions(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                node = document.find("./p:sldSz", p_ns)
                self.assertIsNotNone(node)
                node.attrib["cx"] = "9144000"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def missing_slide_size_node(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                node = document.find("./p:sldSz", p_ns)
                self.assertIsNotNone(node)
                document.remove(node)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def duplicate_slide_size_node(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                node = document.find("./p:sldSz", p_ns)
                self.assertIsNotNone(node)
                document.append(copy.deepcopy(node))
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def extra_slide_size_attribute(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                node = document.find("./p:sldSz", p_ns)
                self.assertIsNotNone(node)
                node.attrib["unregistered"] = "drift"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def default_text_style_english_language(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                node = document.find("./p:defaultTextStyle/a:defPPr/a:defRPr", p_ns)
                self.assertIsNotNone(node)
                node.attrib["lang"] = "en-US"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def default_text_style_theme_font(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                node = document.find(
                    "./p:defaultTextStyle/a:lvl1pPr/a:defRPr/a:latin", p_ns
                )
                self.assertIsNotNone(node)
                node.attrib["typeface"] = "+mn-lt"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def default_text_style_delete_font(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                run = document.find(
                    "./p:defaultTextStyle/a:lvl2pPr/a:defRPr", p_ns
                )
                self.assertIsNotNone(run)
                node = run.find("./a:ea", p_ns)
                self.assertIsNotNone(node)
                run.remove(node)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def default_text_style_interchange_fonts(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                run = document.find(
                    "./p:defaultTextStyle/a:lvl3pPr/a:defRPr", p_ns
                )
                self.assertIsNotNone(run)
                latin = run.find("./a:latin", p_ns)
                east_asian = run.find("./a:ea", p_ns)
                self.assertIsNotNone(latin)
                self.assertIsNotNone(east_asian)
                children = list(run)
                latin_index = children.index(latin)
                east_asian_index = children.index(east_asian)
                run.remove(latin)
                run.remove(east_asian)
                run.insert(latin_index, east_asian)
                run.insert(east_asian_index, latin)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def default_text_style_delete_level(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                style = document.find("./p:defaultTextStyle", p_ns)
                self.assertIsNotNone(style)
                level = style.find("./a:lvl9pPr", p_ns)
                self.assertIsNotNone(level)
                style.remove(level)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def default_text_style_interchange_levels(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                style = document.find("./p:defaultTextStyle", p_ns)
                self.assertIsNotNone(style)
                level8 = style.find("./a:lvl8pPr", p_ns)
                level9 = style.find("./a:lvl9pPr", p_ns)
                self.assertIsNotNone(level8)
                self.assertIsNotNone(level9)
                children = list(style)
                index8 = children.index(level8)
                index9 = children.index(level9)
                style.remove(level8)
                style.remove(level9)
                style.insert(index8, level9)
                style.insert(index9, level8)
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            def default_text_style_wrong_margin(payload: bytes) -> bytes:
                document = ET.fromstring(payload)
                level = document.find("./p:defaultTextStyle/a:lvl9pPr", p_ns)
                self.assertIsNotNone(level)
                level.attrib["marL"] = "0"
                return ET.tostring(document, encoding="utf-8", xml_declaration=True)

            slide_size_controls = (
                (
                    "slide-size-screen4x3",
                    "ppt/presentation.xml",
                    screen4x3_slide_size,
                    "PPTX_SLIDE_SIZE_INVALID",
                ),
                (
                    "slide-size-type-missing",
                    "ppt/presentation.xml",
                    missing_slide_size_type,
                    "PPTX_SLIDE_SIZE_INVALID",
                ),
                (
                    "slide-size-wrong-dimensions",
                    "ppt/presentation.xml",
                    wrong_slide_size_dimensions,
                    "PPTX_SLIDE_SIZE_INVALID",
                ),
                (
                    "slide-size-node-missing",
                    "ppt/presentation.xml",
                    missing_slide_size_node,
                    "PPTX_SLIDE_SIZE_INVALID",
                ),
                (
                    "slide-size-node-duplicate",
                    "ppt/presentation.xml",
                    duplicate_slide_size_node,
                    "PPTX_SLIDE_SIZE_INVALID",
                ),
                (
                    "slide-size-extra-attribute",
                    "ppt/presentation.xml",
                    extra_slide_size_attribute,
                    "PPTX_SLIDE_SIZE_INVALID",
                ),
            )

            default_text_style_controls = (
                (
                    "default-text-style-en-us",
                    "ppt/presentation.xml",
                    default_text_style_english_language,
                    "PPTX_DEFAULT_TEXT_STYLE_INVALID",
                ),
                (
                    "default-text-style-theme-font",
                    "ppt/presentation.xml",
                    default_text_style_theme_font,
                    "PPTX_DEFAULT_TEXT_STYLE_INVALID",
                ),
                (
                    "default-text-style-font-deleted",
                    "ppt/presentation.xml",
                    default_text_style_delete_font,
                    "PPTX_DEFAULT_TEXT_STYLE_INVALID",
                ),
                (
                    "default-text-style-fonts-interchanged",
                    "ppt/presentation.xml",
                    default_text_style_interchange_fonts,
                    "PPTX_DEFAULT_TEXT_STYLE_INVALID",
                ),
            )

            default_text_style_skeleton_controls = (
                (
                    "default-text-style-level-deleted",
                    "ppt/presentation.xml",
                    default_text_style_delete_level,
                    "PPTX_DEFAULT_TEXT_STYLE_INVALID",
                ),
                (
                    "default-text-style-levels-interchanged",
                    "ppt/presentation.xml",
                    default_text_style_interchange_levels,
                    "PPTX_DEFAULT_TEXT_STYLE_INVALID",
                ),
                (
                    "default-text-style-wrong-margin",
                    "ppt/presentation.xml",
                    default_text_style_wrong_margin,
                    "PPTX_DEFAULT_TEXT_STYLE_INVALID",
                ),
            )

            controls = (
                (
                    "unmapped-docprops-label",
                    "docProps/app.xml",
                    unmapped_app_label,
                    "PPTX_DOC_PROPERTIES_INVALID",
                ),
                (
                    "unmapped-titles-label",
                    "docProps/app.xml",
                    unmapped_titles_label,
                    "PPTX_DOC_PROPERTIES_INVALID",
                ),
                (
                    "drift-unmapped-app-field",
                    "docProps/app.xml",
                    drift_unmapped_app_field,
                    "PPTX_DOC_PROPERTIES_INVALID",
                ),
                (
                    "drift-unmapped-core-field",
                    "docProps/core.xml",
                    drift_unmapped_core_field,
                    "PPTX_DOC_PROPERTIES_INVALID",
                ),
                (
                    "arbitrary-theme-name",
                    "ppt/theme/theme1.xml",
                    arbitrary_theme_name,
                    "PPTX_THEME_INVALID",
                ),
                (
                    "legacy-theme-font",
                    "ppt/theme/theme2.xml",
                    legacy_theme_font,
                    "PPTX_THEME_INVALID",
                ),
                (
                    "delete-theme-font-node",
                    "ppt/theme/theme2.xml",
                    delete_theme_font_node,
                    "PPTX_THEME_INVALID",
                ),
                (
                    "arbitrary-theme-scheme",
                    "ppt/theme/theme1.xml",
                    arbitrary_theme_scheme,
                    "PPTX_THEME_INVALID",
                ),
                (
                    "layout-arbitrary-text",
                    "ppt/slideLayouts/slideLayout1.xml",
                    arbitrary_template_text,
                    "PPTX_EDITABLE_TEMPLATE_INVALID",
                ),
                (
                    "layout-arbitrary-name",
                    "ppt/slideLayouts/slideLayout2.xml",
                    arbitrary_template_name,
                    "PPTX_EDITABLE_TEMPLATE_INVALID",
                ),
                (
                    "layout-allowed-name-substitution",
                    "ppt/slideLayouts/slideLayout2.xml",
                    substitute_allowed_template_name,
                    "PPTX_EDITABLE_TEMPLATE_INVALID",
                ),
                (
                    "layout-allowed-layout-substitution",
                    "ppt/slideLayouts/slideLayout2.xml",
                    substitute_allowed_layout_name,
                    "PPTX_EDITABLE_TEMPLATE_INVALID",
                ),
                (
                    "layout-allowed-text-substitution",
                    "ppt/slideLayouts/slideLayout2.xml",
                    substitute_allowed_template_text,
                    "PPTX_EDITABLE_TEMPLATE_INVALID",
                ),
                (
                    "layout-text-deletion",
                    "ppt/slideLayouts/slideLayout2.xml",
                    delete_template_text,
                    "PPTX_EDITABLE_TEMPLATE_INVALID",
                ),
                (
                    "layout-legacy-language",
                    "ppt/slideLayouts/slideLayout3.xml",
                    legacy_template_language,
                    "PPTX_EDITABLE_TEMPLATE_INVALID",
                ),
                (
                    "layout-legacy-font",
                    "ppt/slideLayouts/slideLayout4.xml",
                    legacy_template_font,
                    "PPTX_EDITABLE_TEMPLATE_INVALID",
                ),
                (
                    "master-arbitrary-text",
                    "ppt/slideMasters/slideMaster1.xml",
                    arbitrary_template_text,
                    "PPTX_EDITABLE_TEMPLATE_INVALID",
                ),
                (
                    "master-arbitrary-name",
                    "ppt/slideMasters/slideMaster1.xml",
                    arbitrary_template_name,
                    "PPTX_EDITABLE_TEMPLATE_INVALID",
                ),
                (
                    "master-legacy-language",
                    "ppt/slideMasters/slideMaster1.xml",
                    legacy_template_language,
                    "PPTX_EDITABLE_TEMPLATE_INVALID",
                ),
                (
                    "master-legacy-font",
                    "ppt/slideMasters/slideMaster1.xml",
                    legacy_template_font,
                    "PPTX_EDITABLE_TEMPLATE_INVALID",
                ),
                (
                    "notes-master-arbitrary-text",
                    "ppt/notesMasters/notesMaster1.xml",
                    arbitrary_template_text,
                    "PPTX_EDITABLE_TEMPLATE_INVALID",
                ),
                (
                    "notes-master-arbitrary-name",
                    "ppt/notesMasters/notesMaster1.xml",
                    arbitrary_template_name,
                    "PPTX_EDITABLE_TEMPLATE_INVALID",
                ),
                (
                    "notes-master-legacy-language",
                    "ppt/notesMasters/notesMaster1.xml",
                    legacy_template_language,
                    "PPTX_EDITABLE_TEMPLATE_INVALID",
                ),
                (
                    "notes-master-legacy-font",
                    "ppt/notesMasters/notesMaster1.xml",
                    legacy_template_font,
                    "PPTX_EDITABLE_TEMPLATE_INVALID",
                ),
            )
            for label, member, mutation, error in (
                controls
                + slide_size_controls
                + default_text_style_controls
                + default_text_style_skeleton_controls
            ):
                mutated = root / f"{label}.pptx"
                mutate_zip_member(source, mutated, member, mutation)
                with self.subTest(label=label), self.assertRaisesRegex(
                    VerificationError, error
                ):
                    verify_pptx(mutated, ir)

            for label, member, mutation, _ in slide_size_controls[:2]:
                repaired = root / f"{label}-canonicalized.pptx"
                mutate_zip_member(source, repaired, member, mutation)
                normalize_pptx(repaired)
                with self.subTest(label=f"{label}-canonicalizer-repair"):
                    with zipfile.ZipFile(repaired) as archive:
                        document = ET.fromstring(archive.read("ppt/presentation.xml"))
                    nodes = document.findall("./p:sldSz", p_ns)
                    self.assertEqual(1, len(nodes))
                    self.assertEqual(
                        {"cx": "12192000", "cy": "6858000", "type": "screen16x9"},
                        nodes[0].attrib,
                    )
                    receipt = verify_pptx(repaired, ir)
                    self.assertEqual(
                        {
                            "status": "complete",
                            "cx": 12192000,
                            "cy": 6858000,
                            "aspect_ratio": "16:9",
                            "type": "screen16x9",
                        },
                        receipt["slide_size_closure"],
                    )

            for label, member, mutation, _ in slide_size_controls[2:]:
                rejected = root / f"{label}-canonicalizer-rejected.pptx"
                mutate_zip_member(source, rejected, member, mutation)
                with self.subTest(label=f"{label}-canonicalizer-reject"), self.assertRaisesRegex(
                    VerificationError, "PPTX_SLIDE_SIZE_INVALID"
                ):
                    normalize_pptx(rejected)

            for label, member, mutation, _ in default_text_style_controls:
                repaired = root / f"{label}-canonicalized.pptx"
                mutate_zip_member(source, repaired, member, mutation)
                normalize_pptx(repaired)
                with self.subTest(label=f"{label}-canonicalizer-repair"):
                    receipt = verify_pptx(repaired, ir)
                    self.assertEqual(
                        {
                            "status": "complete",
                            "skeleton": "exact",
                            "semantic_sha256": "sha256:ba07daf19978f92c4d69d62715c037f0c6a7eafbff61cbb4eaad7c2f4d73a10a",
                            "language": "zh-CN",
                            "level_count": 9,
                            "run_properties_count": 10,
                            "font_slot_count": 27,
                            "typeface": "Microsoft YaHei",
                        },
                        receipt["default_text_style_closure"],
                    )

            for label, member, mutation, _ in default_text_style_skeleton_controls:
                rejected = root / f"{label}-canonicalizer-rejected.pptx"
                mutate_zip_member(source, rejected, member, mutation)
                with self.subTest(label=f"{label}-canonicalizer-reject"), self.assertRaisesRegex(
                    VerificationError, "PPTX_DEFAULT_TEXT_STYLE_INVALID"
                ):
                    normalize_pptx(rejected)


if __name__ == "__main__":
    unittest.main()
