# Downstream renderer boundary v1

This reference defines a dormant, specification-only boundary for a future
downstream renderer. It does not authorize or provide an adapter, renderer,
writer, dependency installation, or production export path.

## Boundary

The only permitted direction is:

`released upstream facts/evidence/privacy state -> closed RenderIR -> writer -> atomic artifact bundle`

The writer may consume only RenderIR. It may not read a case file, choose legal
content, infer emphasis, shorten text, change layout, or write upstream state.
RenderIR deliberately contains no source path and no original/extracted
plaintext: only frozen source hashes, locators, three-stage text hashes, and the
minimal display text cross the writer boundary. Source-envelope verification
occurs outside the writer boundary and is never projected to a writer.
The exact canonicalization and digest algorithms are normative in
[`verification-algorithms-v1.md`](verification-algorithms-v1.md).

The contract specifies:

- all seven layouts, including `comparison_table`, and all three time semantics;
- a closed scene graph with element-level source hashes and stable locators;
- explicit visual-mode and three-question human checkpoint state;
- a pseudonymous human confirmation receipt with input hash and revocation state;
- synthetic/deidentified privacy state and mandatory input/output scan gates;
- a closed engine allowlist with layout-to-engine compatibility;
- requested-versus-produced equality, per-artifact SHA-256, one scene-graph
  digest, anchor tolerance, and same-filesystem atomic commit;
- fail-closed behavior for missing formats, unknown fields, unknown engines,
  unconfirmed emphasis, unsafe privacy state, path escape, digest mismatch, and
  geometry drift.

Dates, intervals, and ordinals are bound to an explicit linear axis with a
maximum 0.5-point tolerance. Graph edges bind unique visible line elements with
explicit endpoints. Each endpoint must be inside both the canvas and its line
bbox within 0.25 point. Comparison cells bind `table_cell` elements. No writer
may reconstruct these decisions from labels or recalculate a second layout.

No renderer, external dependency, network access, real-case fixture, installer,
promotion hook, or formal-skill mutation is authorized by this reference.

Graphviz/LibreOffice (`dot`/`soffice`) availability is **DEFERRED / N/A at the
specification layer**. It becomes a REQUIRED environment and failure-injection
gate only for a separately approved future runtime implementation. Structural
contract evidence must never be presented as proof that a real exporter or
production environment passed.

Likewise, `confirmer.human=true`, `atomic_commit.*=true`, and a structurally
valid geometry/privacy receipt are declarations, not proof of a live human,
filesystem transaction, OOXML package scan, exporter roundtrip, or artifact
measurement. A future separately approved runtime implementation MUST add
external identity/interaction evidence, failure-injected atomicity evidence,
real exporter roundtrips, unpacked OOXML privacy scanning, and measured artifact
geometry. All five are DEFERRED / N/A at this specification layer.

## Release semantics

- `pending` checkpoint data can be validated only as a neutral, draft-only
  RenderIR with no emphasized element.
- A final bundle requires an active confirmation receipt whose selected layout,
  visual mode, emphasis IDs, and raw RenderIR hash match the RenderIR.
- Partial success is invalid in this R1 contract. Requested and produced format
  sets must be identical and non-empty.
- Output paths must be relative and contained under the explicit artifact root.
- Output paths must use their unique POSIX spelling: no `.`/`..` segments,
  doubled separators, backslashes, absolute paths, or case-fold collisions.
- Any failed run must emit a closed failure receipt and leave both the formal
  destination and atomic staging area empty; a partial artifact set is not a
  recoverable success state.
- Validation success is structural evidence only; it does not establish factual,
  evidentiary, legal, privacy, or filing correctness.

## Design-source provenance

The behavioral boundary was informed by the public
[`MiaoQichuan/mqc-litigation-visual-redraw`](https://github.com/MiaoQichuan/mqc-litigation-visual-redraw)
repository at commit `9c6558f1094b7ca71fa8ab49c56971985de93fa4`, licensed
under MIT, `Copyright (c) 2026 Miao Qichuan`. This reference and its schemas are
independently written. No donor code, logo, avatar, screenshot, brand treatment,
or marketing expression is included or authorized.
