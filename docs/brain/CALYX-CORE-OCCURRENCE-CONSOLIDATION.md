# CALYX CORE 2 — occurrence persistence consolidation

Date: 2026-08-08
Parent: #384
Primary issue: #386
Related packet: #462
Supersedes overlapping draft implementations: #599 and #610 after successful validation/merge of this replacement.

## Objective

Remove the split occurrence-persistence authority created by two independently correct but incomplete draft lanes:

- PR #610 supplied durable PostgreSQL occurrence staging, checkpoints, canonical IDs, and review persistence, but its reconciliation identity was not bound to exact taxonomy-review evidence.
- PR #599 supplied content-addressed raw/reconciliation identity and fail-closed taxonomy-review semantics, but used a separate local-file workspace and stale taxonomy branch ancestry rather than the merged PostgreSQL taxonomy pipeline.

This current-main replacement combines the strongest properties of both and binds occurrence interpretation directly to the merged taxonomy schema from PR #619 / migration 107.

## Canonical architecture

`bounded occurrence batch + exact completed taxonomy release/review context → immutable reconciliation run → staged occurrence evidence + review queue + checkpoint`

`migrations/108_occurrence_reconciliation_runs.sql` adds staging-only PostgreSQL tables:

- `occurrence_pipeline.reconciliation_runs`
- `occurrence_pipeline.staged_occurrences`
- `occurrence_pipeline.review_queue`
- `occurrence_pipeline.checkpoints`

Corrective migration `109_occurrence_taxonomy_context_guard.sql` adds a database-level trigger requiring the selected taxonomy release to have:

- a valid staged/review-required/reviewed release state;
- a completed `taxonomy_pipeline.staging_checkpoints` row;
- the exact source SHA-256 recorded by the taxonomy release.

This closes a static-review defect found before executable CI: the initial consolidation could otherwise have persisted occurrence interpretation against a partially staged taxonomy release if at least one staged taxon existed.

Every run stores:

- bounded input-batch SHA-256;
- exact taxonomy release ID;
- taxonomy source SHA-256;
- deterministic digest of taxonomy review evidence and review status;
- open taxonomy-review count;
- combined taxonomy-context SHA-256;
- reconciliation schema version.

The run ID is derived from the source, job key, exact input-batch digest, exact taxonomy-context digest, and schema version. Reprocessing identical occurrence evidence against changed taxonomy/review evidence therefore creates a new immutable run instead of overwriting prior scientific interpretation.

## Taxonomy reconciliation

`runtime/occurrence_persistence.py` reads only the merged `taxonomy_pipeline` staging/review schema.

Resolution is fail-closed:

- exact supplied taxon key resolves only when it is unique and not implicated in an open taxonomy review;
- exact scientific name resolves only when it maps to one canonical staged taxon and is not implicated in an open taxonomy review;
- ambiguous names enter occurrence review;
- open duplicate/accepted-name taxonomy review evidence can force `taxonomy_review_required`;
- resolved/dismissed taxonomy review records remain part of the context digest but do not block matching;
- the database refuses to create a reconciliation run until taxonomy staging is complete.

This preserves historical evidence when taxonomy review status changes and prevents partial taxonomy state from becoming occurrence evidence.

## Occurrence evidence

Each staged record preserves:

- source and stable source record ID;
- scientific/accepted name and supplied taxon key;
- canonical taxon ID when resolved;
- reconciliation state/method;
- coordinates and uncertainty state;
- locality, event, collector, license and basis-of-record fields;
- full raw JSON evidence;
- raw SHA-256;
- normalized payload containing the exact taxonomy release/context binding.

Invalid coordinates do not erase an otherwise valid taxon reconciliation; they produce a separate review reason.

## Replay and historical integrity

Exact replay of an existing input/taxonomy context returns the existing run and does not duplicate staged rows. A changed taxonomy release, open review item, or review status changes the taxonomy-context digest and therefore generates a distinct run while leaving prior rows unchanged.

The schema deliberately keys staged and review rows by `run_id`, not merely source record ID. This prevents a new taxonomy interpretation from mutating historical occurrence evidence.

## Validation contract

Dedicated workflow: `.github/workflows/calyx-occurrence-consolidated-validation.yml`.

PostgreSQL 16 tests cover:

- migration 107 → 108 application;
- migration 109 rejection of incomplete taxonomy staging;
- migration 109 acceptance of completed review-required taxonomy;
- taxonomy source-SHA mismatch rejection;
- exact replay idempotency;
- exact taxonomy-release binding;
- changed taxonomy-review evidence creating a new run;
- preservation of the old reconciliation state after taxonomy review changes;
- resolved taxonomy review not blocking clean matching;
- invalid-coordinate review without loss of taxon resolution;
- existing bounded occurrence-staging regression;
- compile, Ruff, diff hygiene and permanent non-authority assertions.

Executable validation evidence must come from real workflow steps. `steps=null`, `action_required`, or zero-job runs are infrastructure evidence only and may not be represented as a pass or code failure.

Initial PR #732 head `6154364c528b1781b9587998ec6bf7c1a9ca9440` triggered dedicated run `31290627123`; job `93187001446` failed before step 1 with `steps=null`. This reproduces repository CI incident #481 and is not a code verdict. The branch was then hardened with the migration-109 taxonomy-completeness guard before further expansion.

While the branch was being built, `main` advanced by 11 commits to `7f5bec2fb8092739a8e5fc5ce55ebc9008a9171e`. Comparison showed the intervening changes were confined to the Reasoning Ledger prerequisite activation gate and did not overlap this occurrence surface.

## Governance boundary

This replacement has no operation that:

- activates taxonomy;
- promotes a taxonomy release;
- mutates `oc_graph` or the production Knowledge Graph;
- publishes scientific conclusions;
- performs an unbounded GBIF/iNaturalist harvest;
- deploys production code;
- approves review items.

`automatic_promotion=false` is enforced at the database layer for every reconciliation run.

## Release plan

1. Obtain executable exact-head CI for this replacement.
2. Fix any demonstrated failures before expanding scope.
3. If green, make this the single authoritative occurrence-persistence PR.
4. Close #599 and #610 as superseded without merging their divergent implementations.
5. Merge this replacement only after exact-head validation and ordinary review gates are satisfied.
6. Continue #386 toward its remaining owner-governed taxonomy activation/species-API proof; no activation is authorized by this build.
