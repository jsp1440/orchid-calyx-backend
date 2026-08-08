# CALYX occurrence persistence — issue #462

Date: 2026-08-08
Depends on: #461 taxonomy release intake and reviewed staging
PR: #599 (draft; intentionally unmerged)
Status: implementation advanced with taxonomy-bound immutable reconciliation; final executable CI currently BLOCKED by repository-wide GitHub hosted-runner failure before first step.

## Goal

Provide the durable, bounded occurrence path required by the Accelerated Core without performing an unbounded harvest, taxonomy activation, production relinking, Knowledge Graph mutation, deployment, merge, or publication.

Lifecycle:

`bounded GBIF/iNaturalist records → immutable raw batch → taxonomy/review-bound reconciliation run → deterministic normalization → review queue → resumable staging projection → protected readiness`

## Existing bounded intake contract

`runtime/occurrence_persistence.py` accepts only explicit caller-supplied record arrays for `gbif` or `inaturalist`.

Default limits remain:

- maximum 5,000 records per intake;
- maximum 25 MiB serialized content;
- stable source identifier required per record;
- duplicate source identifiers fail closed;
- no network harvester exists in this slice.

The raw JSONL batch is content-addressed by SHA-256 and immutable. `unbounded_harvest_authorized=false` remains permanent.

## 2026-08-08 provenance hardening

### Defect found

The original #462 implementation derived `batch_id` only from immutable raw occurrence bytes but stored `normalized.jsonl`, the reconciliation manifest, review queue, and staging checkpoint directly under that batch directory.

That was insufficient once #461 became a real versioned taxonomy source. Reprocessing the same GBIF/iNaturalist raw batch against a changed taxonomy staging artifact could preserve the same raw `batch_id` while replacing the earlier derived reconciliation evidence. The raw source remained immutable, but the scientific interpretation was not independently immutable.

### Corrected two-level identity

The implementation now separates:

1. **raw occurrence batch identity** — source + raw occurrence SHA-256; and
2. **reconciliation run identity** — SHA-256 bound to:
   - raw occurrence SHA-256;
   - exact taxonomy staging SHA-256;
   - exact taxonomy review-queue SHA-256 when present;
   - pending taxonomy-review count;
   - occurrence schema version.

A reconciliation receives a deterministic `recon-<digest>` run ID. Derived artifacts are stored under:

`batches/<batch_id>/runs/<run_id>/`

The same raw occurrence batch reconciled against a different taxonomy/review state therefore creates a different immutable run instead of overwriting earlier evidence. Replaying the same raw batch against the same taxonomy/review state resolves to the same run.

`latest_run.json` is only an operator convenience pointer; the immutable run artifacts remain addressable by exact `run_id`.

### Taxonomy evidence provenance

Every reconciliation manifest/readiness response now exposes a taxonomy context containing:

- staging filename;
- staging SHA-256;
- review-queue filename when present;
- review-queue SHA-256 when present;
- pending taxonomy-review count;
- deterministic combined taxonomy-context SHA-256.

Every normalized occurrence row also carries that taxonomy-context digest.

This prevents an occurrence record from appearing canonically reconciled without recording which reviewed taxonomy evidence was used.

## Review-aware canonical reconciliation

The #461 real August release has an explicit pending review queue. Occurrence reconciliation now consumes a sibling `review_queue.json` when the configured taxonomy staging artifact provides one.

Pending taxonomy items are indexed by taxon key and normalized scientific name. An occurrence that would otherwise match a pending taxonomy item is classified:

`taxonomy_review_required`

rather than `matched`.

The occurrence enters its own read-only review queue with reason:

`taxon_taxonomy_review_required`

Resolved/non-pending taxonomy review entries do not block exact matching.

This closes the scientific-governance gap where the two duplicated `Gastrochilus wenchuanensis` rows or another pending #461 anomaly could otherwise be treated downstream as a clean canonical identity merely because the staging JSONL contained it.

No fuzzy taxonomic inference is added. Resolution order remains conservative:

1. pending taxonomy-review block by exact supplied key;
2. pending taxonomy-review block by exact normalized scientific name;
3. exact supplied canonical key;
4. exact normalized scientific-name match;
5. ambiguous exact-name review;
6. unmatched review.

## Coordinate and source provenance

Normalized occurrence evidence continues to preserve:

- source and source record ID;
- original source object;
- scientific name and supplied taxon key;
- canonical taxon ID only for an allowed exact match;
- reconciliation state/method;
- decimal latitude/longitude;
- coordinate uncertainty;
- coordinate validity state;
- event date;
- country code;
- basis/quality record;
- deterministic row SHA-256.

Invalid or partial coordinates remain evidence but are classified explicitly; invalid coordinates enter review rather than being silently accepted.

## Resumable idempotent staging

Each reconciliation run owns its own checkpoint and staging artifact. `project_staging()` remains bounded to 1–5,000 rows per call and records:

- next offset;
- completion state;
- projected unique row count;
- normalized artifact digest.

Rows are keyed by row SHA-256 so replay of a completed run adds zero duplicate rows.

Historical runs can now be selected explicitly by `run_id` instead of being inaccessible once a newer taxonomy reconciliation becomes the latest run.

## Protected Mission Control API

Owner/API-key-protected routes remain under:

`/brain/mission-control/occurrences`

- `POST /intake` — bounded GBIF/iNaturalist intake; returns both `batch_id` and exact `run_id`;
- `POST /{batch_id}/stage` — bounded projection; optional `run_id` selects an exact historical reconciliation;
- `GET /{batch_id}/review-queue` — bounded read-only queue; optional `run_id`;
- `GET /{batch_id}/readiness` — readiness/evidence for latest or exact `run_id`.

The request still cannot supply arbitrary taxonomy server paths. Taxonomy staging is operator configured through `CALYX_TAXONOMY_REVIEW_STAGING_PATH`.

## Test expansion

The focused suite was expanded to prove:

- immutable raw occurrence replay;
- deterministic taxonomy-context digests;
- same raw occurrence batch + same taxonomy => same reconciliation run;
- same raw occurrence batch + changed taxonomy => different reconciliation run;
- first reconciliation manifest remains byte-identical after the second run;
- exact historical readiness remains addressable;
- pending taxonomy review blocks canonical matching;
- resolved taxonomy review does not block matching;
- malformed/non-array taxonomy review sidecars fail closed;
- existing GBIF/iNaturalist normalization, coordinate, boundedness, source-ID, staging, API, and non-authority contracts remain covered.

## Validation state

Before this hardening, exact head `0fdaa12b84b5cf1036596c85822464a83edf6fa6` passed all five triggered workflows, including `CALYX Occurrence Persistence 462` run `31238432692`.

The 2026-08-08 hardening commits are:

- `a5082233b073a01fcfd12ff53b8e33d1257f1786` — immutable taxonomy-bound reconciliation runs and taxonomy-review blocking;
- `fa0723e68f43a349c7e20f2e720812784d40025a` — expanded deterministic regression suite;
- `1524386ed36d0808b8b00579e303428672e829f3` — protected exact-run selector in Mission Control.

### Current CI infrastructure blocker

The first hardening cycle (`fa0723e...`) emitted all expected workflows, but every job failed before a first workflow step existed. For example:

- occurrence run `31281338894`, job `93163085738`: `steps=null`, no downloadable job log blob;
- workflow-governance run `31281338895`, job `93163085992`: `steps=null`.

A retry of the occurrence workflow again produced a no-step job (`93163156747`).

The pattern is not specific to #599. Independent BUILD-BRAIN-114N head `f5c92b62a95b34982edaf376fb527d474140d681` simultaneously showed the same pre-step failure across its proposal-authorization, workflow-governance, BUILD-088E, and CALYX-AGENT workflows; proposal-authorization job `93162306519` also had `steps=null`.

The subsequent exact #599 head `1524386e...` again produced five immediate pre-step failures, including occurrence run `31281480675`.

Therefore these failures are recorded as repository/GitHub hosted-runner provisioning failures, **not executable evidence that the changed Python/tests failed**. They are also not counted as passing validation. Final DELIVERED status for the hardening requires a future exact-head executable cycle once hosted runners actually start steps.

No validation requirement has been weakened to bypass this outage.

## Permanent non-authority

Readiness continues to return:

- `ready_for_publication=false`;
- `knowledge_graph_mutation_authorized=false`;
- `taxonomy_activation_authorized=false`;
- `unbounded_harvest_authorized=false`.

There is no production graph writer, production occurrence writer, taxonomy activator, publication endpoint, or network harvester in this slice.

## Integration posture

PR #599 remains intentionally stacked on the #461 feature branch because #462 consumes the reviewed taxonomy identity artifact introduced there. #461 has since advanced with real May→August Hassler evidence; the occurrence contract consumes the resulting JSONL/review-queue shape without requiring taxonomy activation.

Neither #461 nor #462 is to be merged under their build-packet instructions. These are review-ready implementation packets, not authorization to activate taxonomy or occurrences.

## Explicit non-actions

This work does not:

- harvest GBIF or iNaturalist over the network;
- fabricate occurrence counts;
- activate the August taxonomy release;
- resolve the three pending August taxonomy findings;
- relink production records;
- write production occurrence tables;
- mutate `oc_graph`;
- publish scientific conclusions;
- deploy;
- merge.
