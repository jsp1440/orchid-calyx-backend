# CALYX taxonomy release intake — issue #461

Date: 2026-08-07
Issue: #461
PR: #598 (draft; intentionally unmerged)
Status: real August source received and parser/staging contract validated; active-release comparison BLOCKED pending a genuine prior active Hassler release artifact.

## Goal

Provide the real-release-ready intake path for a caller-supplied Hassler WorldOrchids/World Plants release without inventing source evidence and without giving repository code taxonomy activation authority.

## Real August 2026 source evidence

The exact acceptance-target release has now been supplied to the project workflow as:

`WorldOrchids 26-08 (Aug 2 2026)(1).csv`

Observed immutable source evidence:

- raw byte count: **11,529,836**;
- raw SHA-256: **`e5be9268e1a48cb0e1777137ac386a9a870f3581c35f10678c9b810c59688c6f`**;
- content-derived release ID: **`rel-e5be9268e1a48cb0e177`**;
- data rows: **34,724** plus the header;
- header fields: `Taxon|Number|Name|Literature|TrivialName|Distribution|Synonyms|Status|Remarks|ConservationStatus|Photo|Orientation|Author`;
- source rows have a 22-field physical layout because Hassler repeats `Photo / Orientation / Author` triplets beyond the 13-field header;
- zero non-empty source cells fall beyond the canonical 22-field expansion.

### Encoding evidence

The release is predominantly UTF-8 but contains **293 isolated legacy single-byte characters**. Direct strict UTF-8 decoding fails. The intake parser therefore uses UTF-8 `surrogateescape` to preserve valid UTF-8 multibyte sequences and maps only isolated invalid bytes one-to-one to Latin-1 characters. This is deterministic and preserves the original raw bytes separately as the immutable source artifact.

### Hassler rank distribution

The source `Taxon` rank codes resolve to:

- species (`S`): **32,108**;
- variety (`V`): **1,040**;
- subspecies (`SS`): **738**;
- genus (`G`): **732**;
- subtribe (`ST`): **55**;
- form (`FM`): **23**;
- tribe (`T`): **22**;
- subfamily (`SF`): **5**;
- family (`F`): **1**.

The source `Status` field is blank on all 34,724 records. For this recognized Hassler layout, accepted-record status is therefore derived from the known `Taxon` rank codes rather than treating the release as 34,724 unresolved records.

### Synonyms and media

Hassler encodes synonyms inside the `Synonyms` field rather than as separate synonym rows. The real release contains:

- rows carrying embedded synonym text: **19,219**;
- embedded synonym names/markers: **60,984**;
- separate synonym rows: **0**.

The release media slots are:

- `Photo`: **5,121** populated;
- `Photo2`: **2,988** populated;
- `Photo3`: **364** populated;
- `Photo4`: **99** populated.

The intake contract therefore reports `synonym_count` as the embedded Hassler synonym-name count for a Hassler release while preserving `synonym_row_count` separately.

### Review findings from the real release

Rank-aware validation found three records that must remain in explicit review rather than being silently accepted:

1. two identical accepted records for **`Gastrochilus wenchuanensis P. Y. Wu &amp; C. Y. Zhou`**, creating one duplicated taxon key represented by two review-queue items;
2. one species-like name, **`Lepanthes o A. Doucette`**, that fails the rank-aware Hassler species-name contract.

The intended real-release review queue is therefore **3 row-level review items**: two `duplicate_taxon_key` items plus one `malformed_taxon_name` item. No review decision is fabricated by the intake system.

## Actual-file-driven parser corrections

The real source exposed issues that the earlier synthetic fixtures could not demonstrate. PR #598 was hardened to:

- support the mixed UTF-8/legacy-byte source without corrupting valid UTF-8;
- recognize the headered Hassler `Taxon / Number / Name` layout;
- expand repeated `Photo / Orientation / Author` triplets deterministically to the observed 22-column row width;
- derive Hassler taxon rank and accepted-record status from the known `Taxon` codes when `Status` is blank;
- preserve Hassler `Number` where present and fall back to scientific-name identity for species-like records that lack it;
- report the actual embedded-synonym model rather than falsely reporting zero synonyms;
- use rank-aware malformed-name validation so genera and valid hybrid notation are not over-flagged by the generic species heuristic;
- place duplicate taxon keys and rank-aware malformed names into the bounded read-only review queue;
- canonicalize a configured prior baseline through the same mixed-encoding/layout adapter before candidate-vs-baseline comparison.

Generic headered CSV fixtures remain supported; these Hassler-specific rules activate only for the recognized Hassler layout.

## Deterministic artifacts

The current real-source canonicalization produces:

- canonical UTF-8 source SHA-256: **`e7ba31a1f5ab2361f754bcc81a50b38750a986cacf36e180cc72027b5f202be6`**;
- normalized JSONL SHA-256: **`9928fe9fc1e71d0fa987e49ed2c563320fba1a8b980318f58f892e0a3c3313e2`**.

These are derived artifacts. The raw source SHA-256 remains the immutable release identity.

## Content-addressed immutable intake

`runtime/taxonomy_release_intake.py` derives release identity from the raw source SHA-256. Original bytes are preserved under a content-addressed release directory. A replay of identical content resolves to the same release identity and conflicting replacement is rejected.

The canonical source is a normalized UTF-8 pipe-delimited projection used for validation. It does not replace or alter the immutable original source.

## Active-release comparison

Mission Control reads the active comparison source only from operator configuration:

`CALYX_TAXONOMY_ACTIVE_BASELINE_PATH`

The upload request cannot supply an arbitrary server-side comparison path. A configured baseline is canonicalized through the same source adapter before deterministic comparison.

A search of the connected Google Drive, the `WorldPlants Orchid Project` location exposed there, the Orchid Continuum file index, and repository history did **not** locate a genuine prior active WorldOrchids release CSV suitable for authoritative comparison. Therefore no added/removed/changed counts are claimed yet.

This is now the sole dataset-evidence blocker for the comparison phase: **the August source is present; the prior active baseline artifact is not grounded.**

## Review and staging contract

Each normalized row carries:

- source row number;
- canonical taxon key;
- scientific name;
- taxonomic status;
- taxon rank and Hassler rank code when applicable;
- Hassler number when supplied;
- preserved normalized source record, including repeated photo slots;
- deterministic row SHA-256.

`project_staging()` projects normalized records into a local review staging artifact in batches of 1–5000 rows. A durable checkpoint records next offset, normalized artifact digest, unique projected-row count, and completion. Row digests make replay idempotent.

This staging artifact is intentionally not the production taxonomy database and does not relink downstream data.

## Protected Mission Control API

`app/routers/taxonomy_release_intake.py` exposes owner/API-key-protected routes under:

`/brain/mission-control/taxonomy/releases`

- `POST /intake` — bounded multipart source intake and configured-active-baseline comparison;
- `POST /{release_id}/stage` — bounded staging projection;
- `GET /{release_id}/review-queue` — bounded read-only review queue;
- `GET /{release_id}/readiness` — protected release evidence/readiness state.

The router is mounted through `app/routers/live_mission_control.py` and uses the existing `verify_owner_or_api_key` dependency.

## Permanent non-authority

Readiness can become `REVIEW_ONLY`; it cannot become taxonomy-promotion authority. The contract permanently returns:

- `ready_for_promotion=false`;
- `taxonomy_activation_authorized=false`;
- `production_relink_authorized=false`;
- `knowledge_graph_publication_authorized=false`.

No production DB connection or Knowledge Graph publisher is present in the intake service.

## Validation history

Earlier validation exposed and repaired real defects instead of suppressing them:

- `31237084522`: functional tests passed but Ruff caught import-format debt;
- `31237320818`: a new test caught unfamiliar status values escaping the unresolved queue;
- implementation head `525cb260cf47a56939f2ba6d146cc2c092361a0a` subsequently passed all five triggered lanes;
- real-file support initially passed 8 tests but Ruff again caught one import-format issue;
- implementation head `589651fc53c5910762a0d384df39e9620ded41d8` passed the full five-lane matrix after mixed-encoding/Hassler-layout support and source-aware baseline handling.

On exact current implementation/test head **`367c0f6a8b0b68569eff74dafe2ebac1755677c2`**, all five triggered lanes passed:

- CALYX Taxonomy Release Intake 461 **`31242449335`** — success;
- CALYX Workflow Governance Audit **`31242449348`** — success;
- BUILD-088E Validation **`31242449343`** — success;
- CALYX-AUTONOMY-DEPLOYMENT-001 **`31242449341`** — success;
- CALYX-SUPERVISED-PILOT-001 **`31242449336`** — success.

The dedicated taxonomy lane includes compile validation, deterministic generic and actual-Hassler-layout tests, permanent non-authority assertions, Ruff, and diff hygiene.

This Brain update creates a new final documentation head and therefore requires its own exact-head CI cycle before the draft is considered internally validated.

## Remaining work before any activation decision

1. Ground the genuine prior active Hassler/WorldOrchids release artifact.
2. Run deterministic candidate-vs-active comparison and record added/removed/changed evidence.
3. Run the complete August release through the protected intake/staging path and preserve the resulting manifest/review/staging receipt in the target runtime environment.
4. Review the three currently identified row-level issues plus any baseline-comparison conflicts.
5. Only after those steps may a separate owner-governed activation operation even be considered.

## Explicit non-actions

This work does **not** activate taxonomy, relink production records, publish the Knowledge Graph, perform a production migration, deploy, provision Azure, or publish scientific conclusions. Issue #461 explicitly says not to merge; PR #598 remains draft/unmerged unless that issue-level governance instruction is separately changed.