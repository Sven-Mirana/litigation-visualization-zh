# Python-pptx Runtime Boundary

Status: normative for the R4 public-source client-delivery runtime.

## 1. Purpose

The R4 editable-PPTX route MUST be reproducible outside the Codex private runtime. Its only direct
PPTX authoring dependency is `python-pptx==1.0.2`, installed by the operator into an isolated Python
environment outside the repository. The package does not vendor third-party wheels, source trees or
license files and does not perform network installation at runtime.

## 2. Allowed dependency boundary

- Direct editable-PPTX dependency: `python-pptx==1.0.2` (MIT).
- Direct deterministic preview/font-metrics dependency: `Pillow==12.2.0` (MIT-CMU).
- Direct schema-validation dependency: `jsonschema==4.26.0` (MIT).
- Expected transitive dependencies, not vendored: lxml 6.1.1 tested (BSD-3-Clause), Pillow 12.2.0
  tested (MIT-CMU), XlsxWriter 3.2.9 tested (BSD-2-Clause), and typing-extensions 4.15.0 tested
  (PSF-2.0). The corresponding python-pptx requirements are respectively >=3.1.0, >=3.3.2,
  >=0.5.7 and >=4.9.0.
- Standard-library ZIP/XML/hash/path/process facilities may be used for deterministic packaging and
  independent verification.
- The tested jsonschema transitive set is attrs 26.1.0, jsonschema-specifications 2025.9.1,
  referencing 0.37.0 and rpds-py 0.30.0 (all MIT).
- Playwright 1.59.0 is a direct conditional dependency when HTML is requested; its tested transitive
  set is pyee 13.0.1 (MIT) and greenlet 3.5.1 (MIT AND PSF-2.0). The Chrome/Chromium
  executable is host-provided. Neither is part of the PPTX route or embedded in client output.

The operator MUST retain the notices supplied with the exact installed dependency versions. A future
fully locked release SHOULD add a separately reviewed hash lock for direct and transitive wheels;
`requirements-client-delivery.txt` pins the complete tested Python runtime set but is not a wheel-hash
lock; a release environment still needs separately reviewed wheel hashes or an equivalent provenance
receipt.

## 3. Prohibited production dependencies

The executable PPTX surface MUST NOT import, dynamically resolve, invoke or require:

- `@oai/artifact-tool` or any wrapper around it;
- `RUNTIME_NODE`, `RUNTIME_NODE_MODULES`, `RUNTIME_BIN_DIR` or a Codex cache path;
- a bundled Node module used to author the PPTX; or
- a silent alternate writer or flattened full-slide image fallback.

A source or runtime scan that finds a reachable prohibited path is a promotion-blocking HOLD. A
historical mention in a clearly non-executable audit document may remain only when labeled as
historical and excluded from the production dependency proof.

## 4. Native editability

Client-visible titles, body text, dates, tables, relationship nodes, timeline rows, labels and page
furniture MUST be native OOXML objects created through python-pptx or deterministic OOXML post-
processing. Full-slide screenshots and flattened raster pages are not editable PPTX and MUST fail.
Semantic IDs and text-role tokens MUST survive final OOXML extraction and equal the closed
DeliveryIR inventory.

## 5. Deterministic OOXML packaging

After authoring and semantic normalization, the final `.pptx` ZIP MUST be rebuilt using:

- lexicographically sorted member names;
- `ZIP_DEFLATED` with one fixed compression level;
- `date_time=(1980, 1, 1, 0, 0, 0)` for every member;
- fixed `create_system` and `external_attr=0o100600 << 16`;
- no duplicate, absolute, parent-traversal, encrypted or unrecognized relationship members; and
- deterministic normalization of package relationships and creation identifiers before hashing.

Two independent runs in clean output directories MUST produce identical final PPTX bytes. The
verifier MUST inspect the produced archive rather than trust a writer-reported flag.

## 6. Clean-environment gate

The acceptance environment MUST start without Codex Node-module variables. It MUST:

1. create a new virtual environment outside the repository;
2. install `package/requirements-client-delivery.txt` from an approved source;
3. record Python, python-pptx and transitive dependency versions and licenses;
4. run the actual PPTX route, not an import-only smoke test;
5. verify native OOXML, privacy, semantic inventory and deterministic bytes; and
6. show that removing python-pptx fails closed with zero committed client artifacts.

No test may report PASS merely because `import pptx` succeeds.

## 7. Licensing and output boundary

The R4 program and documentation are `GPL-3.0-only`, subject to the preserved historical MIT notices. Python-pptx and its compatible
dependencies remain under their own licenses and are not relicensed by this package. This document
does not determine ownership of case facts, evidence, client materials, fonts or generated content;
those rights and the human client-release gate remain separate.

The GPL license grant permits use, modification and redistribution under its terms. Internal
source-release labels and client/court release gates describe project assurance and professional
responsibility; they are not additional restrictions on GPL rights.
