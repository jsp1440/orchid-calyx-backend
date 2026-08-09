# CALYX CORE 2 — occurrence persistence consolidation

Date: 2026-08-08
Parent: #384
Primary issue: #386
Related packet: #462
Candidate replacement PR: #732

## Objective

Remove the split occurrence-persistence authority created by two independently useful but incomplete drafts:

- #610 supplied durable PostgreSQL staging/checkpoints/review persistence but did not bind reconciliation identity to exact taxonomy-review evidence.
- #599 supplied content-addressed reconciliation and fail-closed taxonomy-review semantics but used a local workspace and stale taxonomy ancestry.

The replacement binds bounded occurrence evidence to the merged #619 `taxonomy_pipeline` release/review evidence and preserves historical interpretations as immutable reconciliation runs.

## Canonical architecture

`bounded occurrence batch + exact completed taxonomy release/review context → immutable reconciliation run → source-taxonomy match/review evidence + checkpoint`

Migration 108 adds staging-only PostgreSQL tables:

- `occurrence_pipeline.reconciliation_runs`
- `occurrence_pipeline.staged_occurrences`
- `occurrence_pipeline.review_queue`
- `occurrence_pipeline.checkpoints`

Migration 109 adds a database trigger requiring:

- taxonomy release state in `staged`, `review_required`, or `reviewed`;
- a completed `taxonomy_pipeline.staging_checkpoints` row;
- exact taxonomy source SHA-256 agreement.

## Critical scientific identity correction

Static audit found a P1 defect after the first draft was opened: the implementation incorrectly treated Hassler `taxon_code` as a taxon identifier.

That assumption is false. `runtime/world_plants_ingest.py` defines `taxon_code` as the rank code and constrains it to values such as `F`, `G`, `S`, `SS`, `V`, and `FM`. The authoritative World Plants crosswalk logic instead prioritizes a unique non-empty `world_plants_number`, then exact normalized name plus rank.

The replacement was corrected before merge or executable validation:

- provider `taxon_key` is preserved only as provider provenance;
- an explicitly supplied `world_plants_number` may resolve a unique Hassler source record;
- otherwise an exact unique accepted/scientific name may resolve a Hassler source record;
- source matches are stored as release-scoped `source_taxonomy_record_id` plus `world_plants_number` and `source_taxon_rank_code`;
- `taxon_code` is never stored as `canonical_taxon_id`;
- `canonical_taxon_id` remains null until a governed canonical Orchid Continuum crosswalk/activation exists;
- matched rows use `source_matched_canonical_pending` and carry machine blocker `CANONICAL_TAXON_CROSSWALK_NOT_ACTIVATED`;
- ambiguity, unresolved identity, or open taxonomy-review evidence enters the review queue.

This distinction is intentional: a strong Hassler source match is scientific provenance, but it is not permission to manufacture a canonical OC taxon identity.

## Taxonomy context identity

Every reconciliation run stores:

- bounded input-batch SHA-256;
- exact taxonomy release ID and source SHA-256;
- deterministic taxonomy-review digest/status;
- open-review count;
- combined taxonomy-context SHA-256;
- reconciliation schema version.

The run ID is content-addressed from the source/job/input digest/taxonomy-context digest/schema version. A changed taxonomy release or review state therefore creates a new run instead of overwriting historical occurrence interpretation.

## Source-taxonomy matching

Matching is conservative:

1. explicit unique World Plants number, when supplied;
2. unique exact normalized accepted/scientific name;
3. otherwise ambiguous/unresolved review.

Open taxonomy review evidence can force `taxonomy_review_required`. Resolved/dismissed review records remain in the context digest but do not block matching.

No fuzzy name matching is used and provider-specific taxon keys are never assumed to equal World Plants identifiers.

## Occurrence evidence

Each staged row preserves:

- source and stable source record ID;
- provider taxon key separately;
- scientific/accepted name;
- optional supplied World Plants number;
- resolved Hassler source-taxonomy record ID, World Plants number and rank code when available;
- nullable canonical taxon ID;
- reconciliation state/method and canonical-projection blocker;
- coordinates, coordinate uncertainty/state, locality, event, collector, license and basis-of-record;
- full raw JSON plus SHA-256;
- normalized payload bound to exact taxonomy release/context.

Invalid coordinates produce a separate review reason without erasing a valid source-taxonomy match.

## Validation contract

Dedicated workflow: `.github/workflows/calyx-occurrence-consolidated-validation.yml`.

PostgreSQL 16 tests now cover:

- migration 107 → 108 → 109;
- incomplete taxonomy staging rejection;
- taxonomy source-SHA mismatch rejection;
- exact replay idempotency;
- source-taxonomy matching by World Plants number and exact name;
- provider-key/source-taxonomy/canonical-ID separation;
- explicit proof that rank code `S` is never used as taxon identity;
- canonical taxon ID remains null with machine blocker until crosswalk activation;
- changed taxonomy-review evidence creates a distinct run and preserves prior evidence;
- resolved review does not block clean source matching;
- invalid-coordinate review does not erase source-taxonomy match;
- existing bounded occurrence-staging regression;
- compile, Ruff, diff hygiene, and non-authority assertions.

Executable validation evidence must come from real workflow steps. `steps=null`, zero-job, or `action_required` runs are infrastructure evidence only.

## Validation history

Initial #732 head `6154364c528b1781b9587998ec6bf7c1a9ca9440` triggered run `31290627123`, job `93187001446`; it failed before step 1 with `steps=null`.

After the taxonomy-completeness guard, head `b3aaee864d98556c9f7da1fcc84e2ebc3abe592a` triggered run `31290722659`, job `93187242006`; the job and a bounded rerun (`93187377905`) again failed before step 1 with `steps=null`.

Those runs do not validate the code. The subsequent P1 identity correction requires a fresh executable exact-head run before any release decision.

## Governance boundary

This replacement cannot:

- activate taxonomy or create the canonical crosswalk;
- promote a taxonomy release;
- approve review items;
- mutate `oc_graph` / the production Knowledge Graph;
- publish scientific conclusions;
- perform an unbounded GBIF/iNaturalist harvest;
- deploy production code.

`automatic_promotion=false` is database-enforced.

## Release plan

1. Obtain executable exact-head CI on the corrected identity model.
2. Fix demonstrated failures before expanding.
3. If green, make #732 the single occurrence-persistence authority.
4. Close #599 and #610 unmerged as superseded.
5. Merge only through normal validated release governance.
6. Continue #386 toward its remaining canonical crosswalk/activation/species-API proof; those production mutations require their own explicit owner decision.
