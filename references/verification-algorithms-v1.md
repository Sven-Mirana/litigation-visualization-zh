# RenderIR verification algorithms v1

This is the normative, self-contained verification profile for the downstream
renderer boundary. A conforming validator MUST fail closed when any step below
cannot be reproduced. Implementations and evaluation tools remain outside the
writer boundary and are not authorized by this reference.

## Strict JSON and canonical bytes

All JSON inputs MUST be UTF-8 RFC 8259 JSON. Duplicate object keys,
`NaN`, `Infinity`, `-Infinity`, and non-finite derived numbers are invalid.

`R1-CJSON(value)` is produced recursively as follows:

1. Object members are sorted by the Unicode code-point order of their keys.
2. Array order is preserved.
3. No insignificant whitespace is emitted; member and item separators are
   exactly `:` and `,`.
4. Strings use JSON escaping for quotation mark, reverse solidus, and control
   characters; other Unicode characters are emitted directly before UTF-8
   encoding.
5. `null`, booleans, integers, and finite JSON numbers retain their parsed JSON
   value and use the shortest deterministic decimal representation that
   round-trips to that value. A producer MUST NOT use a lexically different
   representation to claim the same digest.

`R1-SHA256(value)` is the lowercase string `sha256:` followed by the SHA-256
hex digest of `R1-CJSON(value)`. A text hash is the same prefix and the SHA-256
of the exact UTF-8 text bytes, without newline or Unicode normalization.

The R1 fixtures use only integer-valued scene coordinates in digest-bearing
positive scenes, avoiding cross-runtime floating-point spelling ambiguity.

## Scene and source-set digests

To compute `scene.scene_graph_sha256`, copy the closed `scene` object, remove
only its top-level `scene_graph_sha256` member, and apply `R1-SHA256` to the
remaining object. No element, ordering, geometry, endpoint, text, emphasis, or
provenance field may be excluded.

To compute `privacy.input_scan.input_sha256`:

1. Require every `sources[i].data_class` to equal
   `privacy.data_class`. R1 does not silently downgrade or mix classes.
2. Sort sources by `source_id` ascending.
3. Project each source to exactly
   `{"source_id": id, "sha256": digest, "data_class": class}`.
4. Apply `R1-SHA256` to the projected array.

Thus changing a source digest or its privacy class changes the aggregate.

## Writer projection and provenance closure

The writer-facing RenderIR contains no source path and no original or extracted
plaintext. A text-bearing element exposes only its approved `display_text` and
`display_text_sha256`; provenance exposes source/locator and the three hashes
`original_text_sha256`, `extracted_text_sha256`, and `display_text_sha256`.
For R1 all three provenance hashes MUST equal the hash of the approved display
text. This deliberately disallows normalization, paraphrase, or truncation in
the donor slice.

The evaluator-only provenance envelope is never projected to the writer. It
MUST contain exactly one occurrence for every tuple
`(element_id, source_id, provenance_ordinal)` and no extra tuple. Each occurrence
binds:

- `original_text` to the unique locator row in the frozen synthetic/deidentified
  source and to `original_text_sha256`;
- `extracted_text` to `extracted_text_sha256`;
- `approved_display_text` to `display_text_sha256` and, for a text-bearing
  element, byte-for-byte to `element.text.display_text`.

Changing extracted/approved plaintext, their hashes, and the scene digest still
fails unless the unchanged frozen source/locator and original-text binding also
verify.

## Active receipt and manifest binding

`revocation.active_receipt_sha256` is computed from a deep copy of the complete
confirmation receipt with only top-level `status` forced to `"active"` and
top-level `revocation` forced to `null`, followed by `R1-SHA256`. The revocation
event remains a separate, later event; `revoked_at` MUST NOT predate
`confirmed_at`.

The success manifest's `confirmation_receipt_sha256` is different: it is the
SHA-256 of the exact raw receipt file bytes. Therefore a receipt with the same
ID but changed confirmer, choice, time, status, or revocation cannot be swapped
without invalidating the manifest.

Layout candidates MUST be the unique complete seven-layout allowlist; visual
mode candidates MUST be the unique complete `qichuan/guizang/baimiao` allowlist.
Emphasis candidates MUST contain exactly one `none` plus only unique IDs that
exist in the current scene. The receipt candidate arrays must equal the
checkpoint arrays and the selected values must bind the RenderIR state.

## Anchor set, lines, and paths

The normalized anchor-set digest is `R1-SHA256` of the ascending array of every
unique scene `element_id`. Each artifact geometry index MUST contain exactly
that set. Its declared maximum delta is recomputed as the maximum absolute
difference across `x`, `y`, `width`, and `height` against the single RenderIR
scene; it must not exceed the declared tolerance.

For a line, both explicit endpoints MUST be within the scene canvas and within
the line element's `geometry` bbox, with an inclusive tolerance of 0.25 point
on each boundary. An edge MUST bind one unique visible line element; a writer
may not infer endpoints.

Every output/evidence path MUST equal its own POSIX-normalized spelling and
contain no absolute prefix, empty/`.`/`..` segment, doubled slash, or backslash.
All paths are also compared after Unicode case-folding.

## Atomic and runtime evidence boundary

Requested, produced, geometry, provenance, and privacy-scan sets must close
exactly. A failure receipt is valid only when the observed formal destination is
empty and a staging path declared deleted does not exist.

The specification layer can verify structure and supplied files only. Values such as
`human=true`, `atomic_commit.committed=true`, and `privacy_output_scan.status`
do not prove a live human, an actual atomic rename, an unpacked OOXML privacy
scan, or a real exporter/roundtrip/geometry measurement. Graphviz/LibreOffice
capabilities are also not exercised. Those external observations are
DEFERRED / N/A here and become REQUIRED gates for any separately authorized
runtime implementation.
