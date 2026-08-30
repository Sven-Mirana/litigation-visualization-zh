#!/usr/bin/env python3
"""Read-only release gate: exact inventory, privacy and isolated-demo scope."""
from __future__ import annotations
import ast
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
VERSION = '2026.08.30-r2-timeline-demo-gpl3'
IR_SHA256 = '9a5d162d532133c32877bc32c2d5add9ada348f3ff971b61e3c1424f3123b894'
EXCLUDED_SEAL = {'PACKAGE-MANIFEST.json', 'PACKAGE-RECEIPT.json', 'SHA256SUMS.txt'}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def require(condition, message):
    if not condition:
        raise SystemExit('PUBLIC-RELEASE-FAIL: ' + message)

def main():
    files = {}
    for path in sorted(ROOT.rglob('*')):
        rel = path.relative_to(ROOT).as_posix()
        if rel == '.git' or rel.startswith('.git/'):
            continue
        require(not path.is_symlink(), 'symlink:' + rel)
        require(not any(p in {'.DS_Store', '__pycache__', 'node_modules', '.venv',
                             'payload-legacy-skill', 'payload-frozen-contract-r2',
                             'evidence'} for p in path.relative_to(ROOT).parts), 'private-or-vendored:' + rel)
        if not path.is_file():
            continue
        require(path.suffix not in {'.pyc', '.pyo', '.zip', '.whl'}, 'cache-or-binary:' + rel)
        files[rel] = digest(path)
        try:
            content = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            require(False, 'non-text-release-payload:' + rel)
        if path == Path(__file__).resolve():
            continue
        patterns = [r'/Users/(?!LOCAL_ACCOUNT_CANARY(?:/|\b))[A-Za-z0-9._-]+/',
                    r'/private/tmp/[^\s\"\']+', r'\b1[0-9]{12}-[a-z0-9]+-(?:codex|hermes|claude-code|user)\b',
                    r'gh[pousr]_[A-Za-z0-9]{20,}', r'-----BEGIN [A-Z ]*PRIVATE KEY-----']
        require(not any(re.search(p, content) for p in patterns), 'privacy:' + rel)
        require('Zhua' + 'nz' not in content, 'account-name:' + rel)
        if path.suffix == '.py':
            ast.parse(content, filename=rel)
    manifest = json.loads((ROOT / 'PACKAGE-MANIFEST.json').read_text())
    require(manifest['version'] == VERSION, 'version')
    payload = {p: h for p, h in files.items() if p not in EXCLUDED_SEAL}
    require(manifest['payload_files'] == payload, 'exact-payload-inventory')
    receipt = json.loads((ROOT / 'PACKAGE-RECEIPT.json').read_text())
    require(receipt['manifest_sha256'] == digest(ROOT / 'PACKAGE-MANIFEST.json'), 'receipt-binding')
    require(receipt['file_count'] == len(files), 'file-count')
    ledger = {}
    for line in (ROOT / 'SHA256SUMS.txt').read_text().splitlines():
        checksum, rel = line.split('  ', 1)
        require(rel not in ledger and '..' not in Path(rel).parts and not rel.startswith('/'), 'ledger-path')
        ledger[rel] = checksum
    require(ledger == {p:h for p,h in files.items() if p != 'SHA256SUMS.txt'}, 'whole-tree-ledger')
    source = json.loads((ROOT / 'SOURCE-BINDING.json').read_text())
    production = source['unchanged_public_r4_production_files']
    require(len(production) >= 15, 'missing-production-baseline')
    require(all(files.get(p) == h for p,h in production.items()), 'production-baseline-drift')
    ir = ROOT / 'package/fixtures/timeline-demo/delivery-ir.json'
    require(digest(ir) == IR_SHA256, 'fixed-synthetic-ir')
    data = json.loads(ir.read_text())
    require(data['data_class'] == 'synthetic', 'data-class')
    publication = json.loads((ROOT / 'PUBLICATION.json').read_text())
    require(publication['repository'] == 'Sven-Mirana/litigation-visualization-zh', 'repository')
    provenance = json.loads((ROOT / 'package/LICENSE-PROVENANCE.json').read_text())
    require(len(provenance.get('entities', [])) >= 10, 'license-entities')
    require(files['LICENSE'] == files['package/LICENSE'], 'gpl-texts')
    require(files['LICENSES/MIT.txt'] == files['package/LICENSES/MIT.txt'], 'mit-texts')
    print(f'PUBLIC-RELEASE-PASS: files={len(files)} exact_inventory=true privacy_hits=0 production_unchanged=true')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
