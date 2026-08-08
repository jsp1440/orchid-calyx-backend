# CALYX taxonomy release comparison — issue #461

Date: 2026-08-07
PR: #598 (draft; intentionally unmerged)
Status: real May baseline and August candidate are both grounded; deterministic comparison complete; taxonomy activation remains unauthorized.

## Grounded source artifacts

### Active-baseline candidate — Hassler 26-05

Source supplied as `Orchids 26-05 (May 20 2026) 3.csv`.

- raw bytes: **11,496,953**
- raw SHA-256: **`df6e220e6f2998dea236e4b4e0d656c4d8344b9e615aaf6eaaab97f7619a122a`**
- data rows: **34,675**
- unique scientific-name keys: **34,675**
- canonical UTF-8 projection SHA-256: **`12b3a5bf980f1a26b4a0ae372a9749a1658c69cb3c8838d5875c74dd775d830a`**
- normalized JSONL SHA-256: **`4b4c97f70f86875d8680f71102094c8aec929ecf534b1d2423bfab7f1a517651`**
- isolated legacy bytes repaired only in canonical projection: **293**
- embedded synonym names: **60,961**
- review finding: row 30,684, `Lepanthes o A. Doucette`, `malformed_taxon_name`

Rank counts: `S=32,058`, `V=1,040`, `SS=738`, `G=733`, `ST=55`, `FM=23`, `T=22`, `SF=5`, `F=1`.

### Candidate — Hassler 26-08

Source supplied as `WorldOrchids 26-08 (Aug 2 2026)(1).csv`.

- raw bytes: **11,529,836**
- raw SHA-256: **`e5be9268e1a48cb0e1777137ac386a9a870f3581c35f10678c9b810c59688c6f`**
- content-derived release ID: **`rel-e5be9268e1a48cb0e177`**
- data rows: **34,724**
- unique scientific-name keys: **34,723**
- canonical UTF-8 projection SHA-256: **`e7ba31a1f5ab2361f754bcc81a50b38750a986cacf36e180cc72027b5f202be6`**
- normalized JSONL SHA-256: **`9928fe9fc1e71d0fa987e49ed2c563320fba1a8b980318f58f892e0a3c3313e2`**
- isolated legacy bytes repaired only in canonical projection: **293**
- embedded synonym names: **60,984**
- review queue: **3 row-level items** — two duplicate-key rows for `Gastrochilus wenchuanensis P. Y. Wu &amp; C. Y. Zhou` (rows 19,063 and 19,069), plus `Lepanthes o A. Doucette` at row 30,728 as `malformed_taxon_name`.

Rank counts: `S=32,108`, `V=1,040`, `SS=738`, `G=732`, `ST=55`, `FM=23`, `T=22`, `SF=5`, `F=1`.

The `Lepanthes o A. Doucette` anomaly already exists in the May baseline, so it is not a newly introduced August anomaly. The duplicate `Gastrochilus wenchuanensis` record is new in August: May contains one copy; August contains two identical copies.

## Deterministic May → August comparison

Comparison uses the same identity semantics as `runtime.taxonomy_preflight.compare_rows` after both Hassler files are canonicalized through the source adapter: case-folded scientific `Name` is the comparison key when the generic preflight has no recognized explicit identifier column.

Result:

- baseline unique taxa: **34,675**
- candidate unique taxa: **34,723**
- added unique names: **65**
- removed unique names: **17**
- changed existing records: **4,461**
- unchanged existing records: **30,197**
- removed ratio: **0.0490%** (`0.0004902668`), below the default 5% fail threshold
- changed ratio: **12.8652%** (`0.1286517664`), below the default 25% fail threshold

The 4,461 changed records must **not** be described as 4,461 taxonomic/nomenclatural changes. Canonical field-level inspection shows the changes are concentrated in descriptive/source metadata:

- `Distribution`: **3,781** changed rows
- `Synonyms`: **562**
- `Remarks`: **141**
- `Literature`: **126**
- `Number`: **34**
- `ConservationStatus`: **31**

A changed row may contribute to more than one field count. No photo/media field differences were observed among the shared-name changed records.

Added ranks: **61 species + 4 varieties**. Removed ranks: **12 species + 4 varieties + 1 genus**.

The machine-readable evidence, including complete added/removed name lists, is preserved at:

`docs/brain/evidence/CALYX-461-HASSLER-26-05-TO-26-08.json`

## Review interpretation

The 65 added and 17 removed comparison keys include a mixture of genuinely new/removed names and nomenclatural/author-citation replacements. Examples visible directly in the diff include `Cattleya meninensis`, `Cattleya regentii`, `Cattleya topazzoana`, `Cattleya × freitasii`, `Chamaeanthus brachystachys`, `Crepidium crenulatum`, `Dendrobium archipelagense`, `Habenaria bennettiana`, `Ophrys × martinii`, and `Telipogon isabelae`, where an older author/citation form is removed and a revised form is added. Therefore raw added/removed counts are release-diff evidence, not by themselves a claim of biological taxon creation/extinction.

`Nidema` also disappears from the removed-name side while August adds `Dinema boothii`, `Dinema mariae`, and `Dinema ottonis`; that pattern requires taxonomic review rather than automatic interpretation by the intake layer.

## Bounded staging proof

A bounded 5,000-row projection of the normalized August release reaches completion in seven checkpoints:

`5,000 → 10,000 → 15,000 → 20,000 → 25,000 → 30,000 → 34,724`.

All **34,724 normalized row digests** are unique for staging purposes, including the two duplicate taxon-key rows because provenance preserves distinct source row numbers. Replaying the entire projection produces **zero additional staged-row digests**.

This is review staging only. It is not the production taxonomy database and performs no downstream relinking.

## Governance state

The prior-baseline artifact blocker is now resolved. The real May and August files are both grounded and comparison evidence is complete.

Remaining work before any activation decision is governance/scientific review, not missing source data:

1. Review the three August row-level queue items.
2. Review the 65 added / 17 removed release keys, especially probable nomenclatural replacements.
3. Review material changes among the 4,461 shared-name records where scientific interpretation is needed.
4. Preserve the real-runtime intake/staging receipt when the protected Mission Control workflow is run in its target environment.
5. Only after review may a separate owner-governed taxonomy activation operation be considered.

Permanent non-authority remains unchanged:

- `ready_for_promotion=false`
- `taxonomy_activation_authorized=false`
- `production_relink_authorized=false`
- `knowledge_graph_publication_authorized=false`

PR #598 remains draft/unmerged because issue #461 requires the agent to stop before merge. No taxonomy activation, production relinking, production database mutation, Knowledge Graph publication, Azure provisioning, deployment, or scientific publication is performed by this comparison work.
