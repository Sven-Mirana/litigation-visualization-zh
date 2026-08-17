#!/usr/bin/env python3
"""R4 public-source static release gate; writes no files."""

from __future__ import annotations

import json
import hashlib
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TEXT_SUFFIXES = {".md", ".txt", ".json", ".py", ".yml", ".yaml"}
FORBIDDEN_FILE_PARTS = {"__pycache__", ".DS_Store"}
FORBIDDEN_TEXT = (
    "GITHUB-UPLOAD-" + "CANDIDATE-HOLD",
    "R" + "8",
    "messages" + ".jsonl",
    "127.0.0.1" + ":8787",
    "Zhua" + "nz",
)
CONCRETE_PRIVATE_PATHS = (
    re.compile(r"/Users/(?!LOCAL_ACCOUNT_CANARY(?:/|\b))[A-Za-z0-9._-]+(?:/[^\s'\"<>]*)?"),
    re.compile(r"/private/tmp/[^\s'\"<>]+"),
)
INTERNAL_MESSAGE_ID = re.compile(r"\b1[0-9]{12}-(?:codex|claude|hermes|user)\b", re.I)
EXPECTED_SYNTHETIC_FIXTURES = {
    "07-诉讼案件办案方案工作底稿.md": "c1e7b75d241eeb5a89d003a9c792fcd8e6bf26bf17d9b74b5c097a88bd94db4a",
    "CLIENT-DELIVERY-PROFILE.json": "3e8ee77a213acf449deef2018726e79dafbda320bc43e88fe782e7854161fc3e",
    "FROZEN-07-MANIFEST.json": "0f74fb76456a0a901cb6d0bfad9233d270d254708d9c294d16d024c4673bf21f",
    "TEXT-PASS-RECEIPT.json": "a47fad30c1b86bcb7db400aad80893eddd20fd99d4da6b544c18a34ebe16227a",
}


def fail(message: str) -> None:
    raise SystemExit(f"PUBLIC-RELEASE-FAIL: {message}")


def main() -> int:
    files: list[Path] = []
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if path.is_symlink():
            fail(f"symlink:{rel}")
        if any(part in FORBIDDEN_FILE_PARTS for part in rel.parts):
            fail(f"forbidden-file:{rel}")
        if path.is_file():
            if path.suffix in {".pyc", ".pyo"}:
                fail(f"bytecode:{rel}")
            files.append(path)

    for path in files:
        if path.resolve() == Path(__file__).resolve():
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"NOTICE", "LICENSE"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            fail(f"non-utf8-text:{path.relative_to(ROOT)}")
        for token in FORBIDDEN_TEXT:
            if token in text:
                fail(f"forbidden-text:{token}:{path.relative_to(ROOT)}")
        for pattern in CONCRETE_PRIVATE_PATHS:
            match = pattern.search(text)
            if match:
                fail(f"private-path:{path.relative_to(ROOT)}")
        if INTERNAL_MESSAGE_ID.search(text):
            fail(f"internal-message-id:{path.relative_to(ROOT)}")

    publication = json.loads((ROOT / "PUBLICATION.json").read_text(encoding="utf-8"))
    if publication.get("target_branch") != "codex/r4-gpl3-update-20260816":
        fail("target-branch")
    if publication.get("pull_request_mode") != "draft":
        fail("pull-request-mode")
    if publication.get("upload_intent") is not True or publication.get("upload_executed") is not False:
        fail("upload-state")

    provenance = json.loads((ROOT / "package/LICENSE-PROVENANCE.json").read_text(encoding="utf-8"))
    if not isinstance(provenance.get("entities"), list) or len(provenance["entities"]) < 10:
        fail("package-provenance-entities")

    fixture_root = ROOT / "package/fixtures/sample-case"
    actual_fixture_names = {path.name for path in fixture_root.iterdir() if path.is_file()}
    if actual_fixture_names != set(EXPECTED_SYNTHETIC_FIXTURES):
        fail("fixture-set")
    for name, expected_sha256 in EXPECTED_SYNTHETIC_FIXTURES.items():
        actual_sha256 = hashlib.sha256((fixture_root / name).read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            fail(f"fixture-hash:{name}")

    print(f"PUBLIC-RELEASE-PASS: files={len(files)} privacy_hits=0 symlinks=0 bytecode=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
