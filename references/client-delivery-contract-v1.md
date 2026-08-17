# Client Delivery Contract v1

Status: S2/R4 public-source contract. This document does not authorize client delivery, court submission, or modification of upstream facts.

## 1. Purpose and precedence

This contract defines the client-delivery layer that consumes an already frozen, privacy-approved litigation working-paper result. It adds a default editable PPTX output and an optional single-file offline HTML output. It does not relax the evidence, privacy, human-review, or atomic-output gates inherited from S1.

The normative schemas are:

- `contracts/delivery-ir-v1.schema.json`
- `contracts/artifact-manifest-v2.schema.json`
- `contracts/failure-receipt-v1.schema.json` (frozen S1 only)
- `contracts/failure-receipt-v2.schema.json`
- `contracts/client-release-receipt-v1.schema.json`

All JSON instances MUST be parsed with duplicate-key and non-finite-number rejection and then validated against JSON Schema draft 2020-12. Unknown properties and unknown slide roles MUST fail closed.

## 2. Format request semantics

When the caller omits a format, the request MUST resolve to exactly `['pptx']`. HTML is optional and MUST be explicitly requested. Valid requests are `['pptx']`, `['html']`, and `['pptx', 'html']`; implementations MUST canonicalize the explicit two-format order to PPTX then HTML.

For a successful run, the ordered set of formats in `requested` MUST equal the ordered set of `format` values in `produced`. `requested_equals_produced` MUST be `true`, `partial_success` MUST be `false`, and every requested format MUST pass all applicable checks before any formal output is committed.

If either requested writer or any downstream check fails, the run MUST:

1. return a non-zero exit code;
2. commit no requested artifact and no artifact manifest;
3. delete the staging directory;
4. preserve the pre-run formal-output inventory byte-for-byte; and
5. emit only a separate permission-restricted failure receipt beside the formal
   output target (a caller may choose an explicit new sibling JSON path).

Destination/CLI preflight rejection occurs before a transaction begins and may
report only to stderr. Once the input transaction begins, every handled failure
MUST produce the separate receipt; the receipt itself is never placed inside the
client bundle and never overwrites an existing path.

Failure receipt versions coexist and are not interchangeable. The frozen S1
`run_vis.py` route continues to use `failure-receipt-v1`; the S2/R4 client-
delivery route exclusively uses `failure-receipt-v2`. An implementation MUST
NOT auto-upgrade, downgrade, or relabel one version as the other.

A pre-existing formal output directory MUST NOT be merged into or overwritten. The successful commit is one same-filesystem rename from a complete staging directory into an empty formal target.

## 3. DeliveryIR

The sole writer input is `delivery-ir/1.0`. Its exact top-level fields are:

`schema`, `source_schema`, `case_ref`, `data_class`, `release_state`, `input_sha256`,
`profile_sha256`, `profile`, `sources`, `semantic_inventory`,
`profile_consumption`, `source_consumption`, `derived_consumption`,
`domain_projection_partition`, and `slides`.

`source_schema` is a closed `frozen07-source-schema/1.0` object. It carries one
whole-document `variant` and the exact A01/A04/A06/A08/A09 header tuple for
that variant. The only accepted groups are `canonical-v1` and
`legacy-frozen07-v1`; choosing a header independently per anchor, mixing the
two groups, changing one label/order/width, or declaring a variant whose
headers do not equal its schema constants MUST fail before DeliveryIR exists.
Both writers MUST read these source-native headers from the validated
DeliveryIR, render them as closed visible static owners, and the artifact
verifiers MUST reject a different header. A hard-coded canonical header is not
an allowed fallback for a legacy document.

`case_ref` is an anonymous operational identifier. `input_sha256` binds the frozen input bytes. `profile_sha256` binds canonical JSON for the `profile` object and therefore MUST be computed outside that object. Sources carry only a stable ID, hash, data class, and frozen status; they MUST NOT carry an absolute path, original filename, raw source text, credential, personal identifier, or client secret.

The accepted input profile is closed to `schema`, `case_ref`,
`internal_case_id_sha256`, `data_class`, `release_state`, `client_label`,
`matter_label`, `materials_as_of`, `confidentiality`, `prepared_by`,
`executive_summary`, `next_steps`, and `scope_items`. A `brand_profile` or any
other configurable-but-unconsumed parameter MUST fail as an unknown property;
it MUST NOT enter `profile_sha256` while having no observable delivery effect.
`materials_as_of` MUST be an ISO `YYYY-MM-DD` string that also parses as a real
Gregorian calendar date; regex shape or unchecked JSON Schema `format` is not
sufficient.

Slides have exactly `slide_id`, `role`, `title`, `source_refs`, and `content`. The eight closed roles are:

1. `cover`
2. `executive_summary`
3. `relationship`
4. `timeline`
5. `evidence_matrix`
6. `stage_risk`
7. `next_steps`
8. `scope`

The role may repeat when deterministic pagination is needed. Every semantic input item MUST appear exactly once in the ordered logical-slide sequence for its role. Page breaks MUST be derived only from versioned capacity rules, source order, and stable tie-breakers; font measurement or runtime iteration order MUST NOT silently alter item assignment. A page identifier SHOULD be the stable role plus a zero-padded ordinal, for example `timeline-002`.

In `delivery-ir/1.0`, `relationship.parties` and `relationship.chain` are two
independent, source-bound display lists. Their array order and adjacency are not
edges. A renderer MUST NOT infer, draw, serialize, or describe a relationship
edge or connector from that order. This version intentionally has no `edges`
field and its closed schema rejects one. Any future edge-capable DeliveryIR MUST
use a new version with explicit source-bound `source`/`target` semantics and
corresponding independent validation.

Party cards and chain narratives MUST NOT share one relationship slide. Both
content keys remain required, but exactly one is non-empty: party-only pages
contain no chain objects and reference only `A01`; chain-only pages contain no
party objects and reference only `A02`. Parties have a balanced capacity of six
per slide. Chain narratives have a balanced capacity of three per slide, so
four items paginate `2+2` and five paginate `3+2`; a `3+1` singleton
continuation is forbidden. This split is a layout and semantic isolation rule,
not an assertion that the lists are related.

Because A01 is rendered as cards rather than a visible table, every party card
MUST preserve source column order and label every value as `header=value` using
the validated A01 tuple in `source_schema`. Joining bare values without their
canonical or legacy column meaning is semantic loss and MUST fail review.

Each PPTX chain item MUST be a full-width native editable row with an unnumbered
dot in a separate gutter and the exact source text in a native editable body at
16 pt or greater. The renderer and offline HTML MUST preserve source order but
MUST NOT add visible `01/02/03`, ordered-list numbering, arrows, guide lines, or
connectors. Final-OOXML verification MUST enforce the relationship XOR, exact
party/chain object counts, separate marker/body columns, safe bounds
`x=64..1216, y=136..638`, monotonic rows, at least 8 px between adjacent chain
rows, and zero connectors. Artifact QA MUST independently require every chain
body to satisfy `lineCount * resolvedFontSize * 1.25 + 10 <= bbox.height` at a
resolved artifact size whose final-OOXML conversion is at least 16 pt.
Final-OOXML `a:rPr/@sz`, not the source renderer number, is the point-size
authority. Insufficient text capacity fails closed; the writer MUST NOT shrink,
slice, or summarize the text.

Timeline dated events have a capacity of four per slide. The page count MUST be
`ceil(n/4)` and the events MUST be balanced in stable sorted order so page sizes
differ by at most one; specifically, 7 through 11 events paginate as `4+3`,
`4+4`, `3+3+3`, `4+3+3`, and `4+4+3`. For `n > 4`, a singleton continuation is
forbidden. Undated milestones MUST remain distinct from dated events in both
formats and, when present, occupy deterministic milestone-only trailing
timeline slides at the same four-item capacity. They MUST never precede or
share a slide with a dated event. The writer MUST NOT shrink dated-event text
or share its row area with undated content.

Chronology sorts first by normalized date. Events sharing a date MUST preserve
source occurrence order using anchor ordinal, source locator ordinal, and
within-line event ordinal; sorting same-day events by their display text is
forbidden because it invents an unsupported sequence.

Before pagination, every routed markdown occurrence in A01-A09 MUST receive a
stable anchor-relative source locator and SHA-256 over that exact occurrence.
The closed routing matrix is: A01 table row to labeled `parties`; A02 prose line to
`chain` and timeline; A03 prose line to timeline; A04 table row to `amounts`
and timeline; the one authorized legacy A04 trailing qualification to a
separate `amount_notes` source projection (never a timeline item or amount
row); A05 prose line to timeline; A06 table row to matrix and, only
when its source cells trigger the documented condition, `gaps`; A07 prose line
to `evidence_index`; A08 table row to `stages`; and A09 table row to `risks`.
A line or row containing a valid date is consumed by one `dated` timeline
projection; every other eligible timeline item is consumed by one `undated`
projection using the frozen normalizer or allowed table-row summary. Titles,
table headers, separators, and a dated item already consumed as an event MUST
NOT be emitted again as an undated item.

Table shapes are exact within the whole-document variant. `canonical-v1` uses
A01=`主体/角色/要点/来源`, A04=`项目/金额（元）/口径`,
A06=`要件/事实/证据/缺口/状态`, A08=`阶段/动作/出口`, and
A09=`编号/类别/内容/解除条件`. `legacy-frozen07-v1` uses
A01=`角色/主体/说明`, A04=`口径/项目/金额（万元）/说明`,
A06=`要件/事实主张/对应证据/状态/备注`, A08=`阶段/主要动作/时点`, and
A09=`风险事项/等级/说明/处置`. Extra or missing columns, an unrecognized table in a prose-only
anchor, or an unrecognized substantive prose line in a table-only anchor MUST
fail closed before DeliveryIR exists. Slicing a row to a supported prefix is
forbidden. Each table anchor MUST match its versioned exact header tuple and
that header MUST be followed immediately by exactly one separator whose every
cell matches `^:?-{3,}:?$` and whose width equals the header. Missing, forged,
misplaced, or repeated headers/separators fail closed. Equal source values
remain separate occurrences and are disambiguated by their locators. Profile
binding remains separate through the canonical `profile_sha256`; profile
fields are not part of the markdown consumption denominator and instead close
through their own source-before `profile-consumption/1.0` ledger.

The legacy A04 form MUST contain exactly one prose qualification after at least
one complete table row and a blank paragraph boundary. Zero, two, an
interleaved line, or a value forced into a table cell MUST fail. Its four
amount cells are opaque source text: decimal and negative strings, masks, and
non-numeric values are preserved verbatim. No parser, rounding, unit relabel,
or multiplication by 10,000 is authorized. `amount_notes` is an independent
semantic slot/page with its own source hash and semantic projection.

The A06 gap trigger is variant-aware. Canonical rows use `缺口` plus the
documented `状态` markers. Legacy rows inspect only the `状态` column and create
a gap projection only when that cell contains `待` or `缺`; `备注` never creates
a gap, even when its text contains those characters. A07 remains prose/list
only: each nonblank bullet occurrence has its own exact raw hash and locator,
the bullet marker may be removed by the closed normalizer, and source order is
preserved one-to-one in `evidence_index`.

`profile-consumption/1.0` takes the validated profile as its denominator. It
records the five visible cover scalars and every ordered occurrence of
`executive_summary`, `next_steps`, and `scope_items` by field, zero-based source
index, exact UTF-8 value hash, slide, slot, item index, semantic ID, and content
hash. Equal values remain separate occurrences. The visible denominator and
its projection locations MUST each be unique by their stable occurrence key,
MUST have 100% coverage, and MUST be revalidated whenever semantic inventory
is recomputed. Deleting, reordering, whitespace-changing, or otherwise
rewriting a projected occurrence while retaining the old profile ledger is a
stale-ledger failure, even if the rewritten semantic inventory is internally
canonical.

The accepted non-customer controls `schema`, `case_ref`,
`internal_case_id_sha256`, `data_class`, and `release_state` are separately
hashed in `excluded_controls` with the closed reason
`non_customer_visible_control`; they may not silently disappear from the
profile denominator. The verified internal-case binding remains in the
canonical validated profile used for `profile_sha256`, but is never copied to
the public DeliveryIR `profile` object or a customer-visible slide.

Every A01-A09 anchor MUST contribute at least one routed candidate occurrence;
an empty anchor is not 100% coverage. Prose normalization may remove `-` only
for a whitespace-delimited bullet (`^-\s+`) and may remove an unambiguous `·`
bullet. ASCII `.` and full-width `．` are enumeration marks only when followed
by whitespace; only `、` may be an unspaced enumeration mark. The normalizer
MUST preserve an unspaced negative sign and either decimal point; for example
`-100.00元`, `2024.5万元`, and `100．00元` remain byte-for-text exact.

R4 preserves every source star verbatim rather than interpreting Markdown
emphasis. In particular, it MUST preserve `****`, unmatched stars, numeric
masks such as `6222****1234`, and masked evidence labels in prose, tables,
dated events, undated events, and every other view. The frozen S1 builder may
still provide anchor ranges, but its legacy display-text normalizers are not
an R4 content authority.

`source_consumption/1.0` records every candidate occurrence and every declared
projection, including any separately rendered `other_view` projection. Each
projection binds its slide, slot and index to the canonical semantic ID and
content hash. Candidate coverage MUST be 100%, every candidate MUST have at
least one projection, and projection locations MUST be globally unique;
otherwise the DeliveryIR build fails closed. Anchor-level source references or
an inventory recomputed only after rendering are not substitutes for this
source-before consumption ledger.

The ledger also hashes every deliberately excluded nonblank structural
occurrence in `excluded_items`, with a closed `excluded_reason` of
`anchor_title`, `table_header`, or `table_separator`. Blank lines are not
source items. An unrecognized nonblank occurrence has no exclusion reason and
therefore fails the closed routing matrix instead of disappearing silently.
For each anchor, the multiset of `(source_id, exact-line-sha256)` across all
original nonblank lines MUST equal the multiset across candidates plus
excluded items. A prose subheading is neither a section title nor an implicit
exclusion and therefore fails unless a future contract explicitly routes it.

The PPTX timeline MUST use stable vertical event rows, not a horizontal
alternating-axis layout. Every event has a separate native editable date object,
native editable text card, and unnumbered marker. Dates and bodies occupy distinct
columns; row order makes chronology visible. A guide line or marker MUST remain
in the gutter and MUST NOT cross any date, event body, or undated-milestone text
region. The final-OOXML verifier MUST extract those object bounding boxes and
fail closed on missing/duplicate objects, date/body overlap, adjacent-row
overlap, non-monotonic row order, or any guide/marker crossing. Screenshot or
layout-engine overflow checks supplement but do not replace this geometry gate.
Timeline body text MUST export to at least 16 pt in final OOXML.
Every dated-event label is the canonical ten-character `YYYY-MM-DD` value and
MUST remain one line in the bundled LibreOffice interoperability render without
shrinking its 16.5 pt bold text. Its final OOXML `a:bodyPr/@wrap` MUST be
`none`, and `shape width - a:bodyPr/@lIns - a:bodyPr/@rIns` MUST be at least
114 pt at 16.5 pt, scaled proportionally if the writer increases the font.
The current writer provides 117 pt of inner width. This threshold is bound to
the measured 107.269996 pt LibreOffice 26.8 bold date width and retains 6.73 pt
of renderer/font-metric headroom. Missing insets, a different wrap mode, a
non-ISO label, multiple visible runs, or insufficient scaled inner width is
`TIMELINE_LAYOUT_INVALID` and fails closed. This is an interoperability layout
gate only; it does not alter or infer date semantics.
For every event body, the artifact QA layout MUST satisfy
`lineCount * resolvedFontSize * 1.25 + 10 <= bbox.height`; a generic
`overflow=false` field alone is not capacity evidence. Native timeline objects
MUST remain inside `x=64..1216, y=136..638`, with at least 8 px between adjacent
event rows. Markers are unnumbered dots: array order is visible from row
position, but the renderer MUST NOT add an unproven within-day sequence.

The real-point typography capacities are also semantic isolation rules.
Evidence matrix rows, amount rows, amount-note items, and evidence-index items
occupy separate slides with capacities `3`, `3`, `4`, and `4`. Exactly one of
`rows`, `amounts`, `amount_notes`, and `evidence_index` is non-empty. Stage rows and risk rows occupy
separate `stage_risk` slides with capacities `4` and `3`. Next actions and
evidence gaps occupy separate `next_steps` slides with capacities `5` and `4`.
Each corresponding group keeps all keys required but has exactly one
non-empty list. PPTX and HTML MUST use the same DeliveryIR pagination.

Writers MUST NOT slice, drop, summarize, or replace overflowing items. Overflow produces additional slides. DeliveryIR MUST carry a canonical `semantic_inventory` recomputed from the closed, customer-visible fields. Every slide title is a first-class semantic occurrence at slot `title`, index zero. Each entry binds a stable semantic ID to slide, slot, zero-based item index, and full content hash; the ID also contains a short content-hash suffix. PPTX writers MUST attach those IDs to the names of the native visible objects that render the items, and HTML writers MUST attach them as `data-semantic-id` attributes on the visible elements. Verifiers MUST independently extract the artifact-side IDs in document order and compare them with the recomputed source inventory. Unequal counts, missing IDs, duplicate assignments, unexpected IDs, or reordered stable keys are `SILENT_TRUNCATION_DETECTED` and fail the whole run. A count copied from DeliveryIR is not rendered-item evidence.

The semantic inventory MUST be partitioned exactly and mutually exclusively by
three source-before ledgers: markdown `source_consumption`, validated-profile
`profile_consumption`, and closed `derived_consumption`. The derived ledger is
limited to every exact slide title, the three exact `scope-00` review-boundary
items, and at most one exact missing-legal-authority notice. That notice is
allowed only when every A09 source risk projection lacks both `法条` and `法源`.
Its exact value and target location are contract constants, not caller-supplied
reason/hash claims. `domain_projection_partition/1.0` MUST bind the canonical
semantic-inventory hash and prove that the three ledgers are disjoint and that
their union is the complete visible semantic location/hash multiset. Any
unpartitioned item, multiply partitioned item, stale projection, new page,
rewritten title, or self-declared derived exception fails closed.

## 4. PPTX output

PPTX is the default format. Client-visible text, tables, relationship nodes, timeline nodes, status labels, and page furniture MUST be native editable PowerPoint objects. A screenshot, flattened slide image, or full-slide raster is not an acceptable substitute. Relationship slides in `delivery-ir/1.0` MUST contain zero connector objects because the IR has no explicit edges.

The R4 PPTX writer MUST use a separately installed `python-pptx==1.0.2` runtime
and the deterministic OOXML boundary in `python-pptx-runtime-boundary.md`.
Neither the writer nor its execution wrapper may import, invoke, or require
`@oai/artifact-tool`, Codex-private module caches, `RUNTIME_NODE`,
`RUNTIME_NODE_MODULES`, or `RUNTIME_BIN_DIR`. A reachable prohibited dependency
is a promotion-blocking failure, not an optional fallback.

The PPTX writer MUST:

- use only local deterministic resources;
- emit exactly one direct `p:sldSz` in `ppt/presentation.xml`, with the exact
  attribute set `cx=12192000`, `cy=6858000`, `type=screen16x9`;
- embed no macro, OLE object, external relationship, remote font, linked image, source document, or original input;
- give stable object names derived from slide and semantic element IDs;
- include source IDs in object metadata or speaker-note source blocks without embedding raw source text;
- pass package integrity, native-editability, overflow, privacy, and external-relationship checks; and
- keep the machine state `REVIEW_DRAFT` and visibly display its closed Simplified
  Chinese label `审阅稿` unless a valid active human release receipt binds the
  exact artifact hash.

The canonicalizer MUST leave an already closed `p:sldSz` byte-for-byte intact
and may repair only `type=screen4x3` or a missing `type` when `cx` and `cy` are
already the exact closed values. Wrong dimensions, a missing or duplicate
`p:sldSz`, an extra attribute, or an unknown `type` MUST fail closed: the
canonicalizer MUST NOT change canvas geometry. The final verifier independently requires
the unique direct child, the exact attribute set and values, and the integer
ratio identity `cx * 9 == cy * 16`; it MUST NOT infer correctness from
`PresentationFormat`, the writer, or an Office schema-only PASS. Any mismatch
is `PPTX_SLIDE_SIZE_INVALID`. This metadata closure does not authorize changes
to slide coordinates, page geometry, customer-visible text, or DeliveryIR.

The same `ppt/presentation.xml` part MUST carry exactly one
`p:defaultTextStyle`. Its default `a:defPPr/a:defRPr` and all nine level
`a:defRPr` nodes MUST use exact `lang=zh-CN`. Each of the nine level runs MUST
contain exactly one ordered `a:latin`, `a:ea`, and `a:cs` node, each with the
exact attribute `typeface=Microsoft YaHei`; `+mn-*` theme references are not a
closed final value. The direct-child sequence, nine level paragraph attributes,
run attributes, and `solidFill/schemeClr` skeleton are an exact semantic
fingerprint; deleting or interchanging levels or changing a level margin is
invalid rather than repairable. The writer MUST satisfy this before saving, the
canonicalizer MUST close the known pinned-template language/font omissions and
ordering drift, and the final verifier MUST independently reject English
language, theme-font references, missing/duplicate font nodes, or interchanged
font-node order as `PPTX_DEFAULT_TEXT_STYLE_INVALID`.

Every visible PPTX text container MUST carry exactly one stable object-name
role token: `|TEXTROLE|DECK|`, `|TEXTROLE|SLIDE|`, `|TEXTROLE|MID|`,
`|TEXTROLE|BODY|`, or `|TEXTROLE|AUX|`. The writer uses real-point semantic tokens
of `50.25`, `35.25`, `24`, `16.5`, and `9` pt respectively and writes explicit
OOXML point sizes through python-pptx. Final OOXML verification MUST
parse every visible native shape and table run and enforce minimum actual
`a:rPr/@sz` values of 50 pt for deck titles, 35 pt for slide titles, 24 pt for
mid-level headings/status, and 16 pt for substantive body/date/table/boundary
text. AUX is limited to non-substantive furniture. Unmarked visible text,
missing explicit run sizes, or trusting the source `fontSize` instead of OOXML
MUST fail closed. Table headers are bold BODY, not undersized furniture.

Final OOXML verification MUST also rebuild, independently from object names,
the complete expected native object ledger for each slide from DeliveryIR and
closed chrome constants. The extracted `p:sp`, `p:graphicFrame`, and
`p:cxnSp` base-name set and the exact concatenated `a:t` text for every object
MUST equal that ledger. An extra visible text box, an extra non-text shape,
text appended inside an otherwise valid semantic object, or a rewritten
status/date/header/furniture label is
`PPTX_VISIBLE_OBJECT_LEDGER_INVALID`. A text-role token, semantic ID, or
self-reported hash does not make an unlisted object valid.

Speaker notes are customer-visible in presenter and print-notes views, so they
carry the same obligations as slide chrome. Every slide MUST own exactly one
notes part, no notes part may be shared or orphaned, and the notes text MUST
equal, paragraph for paragraph, the source heading `【来源】`, the slide's
ordered `source_refs`, the boundary heading `【使用边界】`, and the boundary
sentence. Every notes run MUST carry `lang=zh-CN` and the delivery typeface in
all three slots, verified per run rather than by an aggregate count, and the
notes part family is subject to the same ordered-content-model check as slides.

Document properties are customer-visible in the application's file-information
and design surfaces. `dc:title`, `dc:subject`, `dc:creator`, `dc:description`,
`cp:lastModifiedBy`, `Application`, `PresentationFormat`, the `HeadingPairs` and
`TitlesOfParts` labels carried over from the generator template, and the theme
part's own name MUST all resolve through the closed Simplified-Chinese display
map, and no document property may contain a legacy English fixed label or a raw
machine enum. This is an exact structural gate, not a blacklist: `HeadingPairs`
MUST be the ordered variant vector `主题/1/幻灯片标题/0`, `TitlesOfParts` MUST
be the one-value `诉讼可视化主题` vector, and arbitrary unregistered English or
Chinese labels are invalid. Both theme parts MUST use that exact theme name;
their color, font and format scheme names are closed Chinese values.
The entire `app.xml` and `core.xml` semantic XML structures are exact closed
sets (with only the verified Slides/Notes counts parameterized): adding or
changing an otherwise unmapped field is invalid.

All customer-editable template surfaces — the eleven slide layouts, slide
master, notes master and both themes — MUST be normalized and verified, not
merely the populated slides. Fixed master prompts, layout names and placeholder
display names use the closed Simplified-Chinese template map. Every existing
`a:rPr`, `a:defRPr` and `a:endParaRPr` in those editable parts carries
`lang=zh-CN` plus exactly one `a:latin`, `a:ea` and `a:cs` default set to
`Microsoft YaHei`; theme-script and bullet defaults use the same typeface.
Source facts, semantic identifiers, relationship types, layout/placeholder
machine enums and field types are not translated. A mutation of text, display
name, language or font in any editable part family MUST be rejected.
Each editable-template and theme part is additionally bound to its exact
namespace-expanded structural fingerprint, including ordered children, exact
text and sorted attributes. Removing a valid node or substituting one
registered Chinese prompt/name for another is invalid even though every
remaining individual value belongs to the display allowlist.

The writer-customized Open XML sequences MUST remain schema ordered. In
`a:rPr`, the fill/effect group precedes `a:latin`, followed by `a:ea` and then
`a:cs`; explicit Latin and East-Asian typefaces remain mandatory. The mainland
China delivery profile uses `Microsoft YaHei` for all three typeface slots and
marks every visible run `lang=zh-CN`; preview substitution does not alter those
final OOXML requirements. In `a:tcPr`,
`a:lnL`, `a:lnR`, `a:lnT`, and `a:lnB` precede the cell fill choice. The
package verifier MUST reject either sequence when reordered. Where OfficeCLI
OpenXML validation is available in the acceptance environment, the final
normalized PPTX MUST additionally return `success=true`, `count=0`, and an
empty error list; application repair on open is not acceptable evidence.

LibreOffice interoperability renders made with the bundled headless runtime
MUST set both `FONTCONFIG_FILE` to that runtime's `fontconfig/fonts.conf` and
`FONTCONFIG_PATH` to its containing `fontconfig` directory. A render that omits
either setting is invalid environment evidence: missing-glyph boxes from such a
run MUST NOT be used to justify changing the product font. A product-font
change requires a same-environment comparison plus final OOXML typeface/theme
inspection and an available-CJK-font check.

Passing a structural PPTX check does not establish legal correctness, client approval, Microsoft PowerPoint compatibility, or permission to deliver.

## 5. HTML output

HTML is an explicit optional format. It MUST be a single self-contained offline file with inline CSS and, if needed, inline SVG. It MUST contain no script element, executable handler, network URL, external font, external stylesheet, linked image, CDN dependency, telemetry, or remote request. All visible and attribute text derived from DeliveryIR MUST be context-escaped.

The HTML document MUST provide print styles and preserve the same ordered logical slides, facts, source references, release state, and deterministic pagination as PPTX. It MUST display the closed Simplified Chinese label `审阅稿` for machine state `REVIEW_DRAFT` unless the same human release conditions are satisfied. That mark MUST be anchored per article — every article carries exactly one `watermark:release-state` static owner — because a document-wide substring can be satisfied by source text alone. Every customer-visible article text occurrence MUST be owned either by one canonical semantic ID or by a closed static role whose ID, exact text, slide location, and order are contract-defined. Every owner carries the exact visible-text hash, and every article carries the ordered owner count and ledger hash. Static parsing and real Chromium MUST independently enumerate visible text and owners, recompute those hashes, and reject unowned text, unknown/duplicate static roles, rewritten owner text, or owner-ledger drift. Appending text inside an already semantic element is still a hash mismatch; semantic ancestry is not an allowlist for arbitrary descendants.

The expected static ledger is rebuilt from DeliveryIR independently of the
writer and binds, per logical page, page index, slide ID, role, total mixed
owner count, and an ordered list of `(owner_ordinal, static_id, exact_text)`.
`owner_ordinal` is measured in the complete semantic-plus-static DOM owner
stream; comparing only the static subsequence is insufficient. The static
HTML parser and Chromium DOM walker enumerate their actual streams separately
and each compares them to this DeliveryIR contract without trusting the other
engine's receipt or the article's self-declared hash. Chromium additionally
requires exactly one release-state watermark per article.
Every slide article has exactly the two ordered classes `slide` and its one
contract role class; adding a second role is invalid. Non-whitespace body text
outside slide articles is also invalid.

The one inline stylesheet is an exact closed artifact and is bound by its
independently verified SHA-256; external stylesheets and inline `style`
attributes are forbidden. The only registered CSS generated content is the
empty decorative timeline marker. Chromium MUST independently inspect the
computed `content` of `::before`, `::after`, and `::marker` on the complete
document and reject every non-empty value, in both screen and print media.
DOM text walking alone is insufficient because pseudo-element text is absent
from `SHOW_TEXT`.

A real bundled Chromium run with networking blocked MUST validate both `screen` and `print` media: horizontal and vertical article overflow, every semantic descendant's page-bound overflow, unregistered visible text, and owner hash failures MUST each be zero, and Chromium's generated PDF page count MUST equal the DeliveryIR slide count. Static HTML inspection alone is insufficient; overflow MUST add DeliveryIR pages, never trigger CSS font shrinking or clipping.

The release watermark, every cover metadata label, each non-cover header role
label, and each footer document label are fixed single-line chrome. Their
computed `white-space` MUST be `nowrap` and their scroll dimensions MUST fit in
both screen and print media. Source-reference footers and semantic cover
eyebrows remain wrappable because they may contain source-authored text.

## 6. Human release gate

In the absence of a valid `client-release-receipt/1.0`, both DeliveryIR and artifacts MUST use machine state `REVIEW_DRAFT`; the visible `审阅稿` mark is mandatory. The fixed customer chrome, confidentiality labels, document properties and release warnings MUST use the closed Simplified Chinese display map; source facts and identifiers MUST NOT be translated by the renderer. A browser preview, a successful render, a room ACK, an agent recommendation, or a QA pass is not a release receipt.

Only a human in an authorized role may issue the receipt. The receipt binds the exact profile hash and every staged artifact hash, and affirms factual/evidentiary review, legal-conclusion review, privacy review, client-label review, hash verification, and release authority. The artifact manifest independently binds the DeliveryIR hash, profile hash, artifact hashes, and release-receipt hash. A changed artifact or profile byte invalidates the release binding and requires a new receipt. The receipt does not hash DeliveryIR and does not contain its own hash, preventing a release-state hash cycle.

R4 synthetic and separately authorized local validation outputs remain machine state `REVIEW_DRAFT` (visibly displayed as `审阅稿`) unless an authorized human separately supplies that receipt. Source publication and client release are separate decisions.

## 7. Real-case validation boundary

A local actual case may be used only after the synthetic gate passes. Its case reference MUST be pseudonymous and its retained evidence MUST be limited to anonymous case reference, input/profile/artifact hashes, schema versions, pass/fail statuses, tool versions, and audit receipt hashes.

The R4 public source tree, Git patch, review logs, and release packet MUST NOT contain the actual-case path, filename, original text, party name, personal identifier, case number, credential, or client material. Actual inputs and generated client artifacts remain in an authorized local case workspace. Reviewers receive redacted visual evidence or hash-bound receipts, never raw case content through the public source tree.

## 8. Hashing and self-reference rule

Hashes are lowercase SHA-256 over exact bytes and use the `sha256:<64 hex>` representation. Canonical JSON hashes MUST use UTF-8, sorted object keys, no insignificant whitespace, and rejection of duplicate keys and non-finite numbers.

No file may carry a field that claims the hash of that same file. In particular:

- `profile_sha256` is outside the profile object;
- the artifact manifest lists artifacts and independent receipts but not the manifest itself;
- a failure receipt does not contain its own hash; and
- a client-release receipt does not contain its own hash.

An outer promotion or audit receipt may hash any of these files after it has been finalized.

## 9. Promotion boundary

These contracts describe the S2/R4 public source distribution stacked on the frozen S1 behavior. Source publication is governed by `PUBLICATION.json`; these contracts do not authorize installation, client delivery, court submission, or release of actual-case material. Those actions require their own human decision and evidence.

## 10. License and professional-responsibility boundary

Candidate-original software and documentation are offered under
`GPL-3.0-only`; compatible, non-vendored dependencies retain their own licenses.
The GPL grant does not license case facts, evidence, personal data, client
materials, trademarks, fonts, or other third-party content. Conversely, the
candidate, promotion and human-release gates in this contract are assurance and
professional-responsibility states and MUST NOT be represented as additional
restrictions on a recipient's GPL rights.
