# BUILD-620-R2 — Matrix / Conservatory Local Observation Bridge

## Status

Reconstructed on `feature/build-620-local-observation-bridge-r2` directly from executable-green BUILD-619-R2 / PR #788. The stale original BUILD-620 stack is not an integration path.

## Purpose

BUILD-620 lets Matrix / Conservatory submit real plant responses into Candidate Knowledge as local evidence without converting a single plant event into a species-wide or canonical causal claim.

The bridge supports:

`plant record → observation event → exact evidence → bounded local scope → Candidate Knowledge → local reasoning context`

It deliberately does **not** perform:

`plant observation → species mechanism`

## Write contract

Protected endpoint:

`POST /api/platform/matrix/local-observation`

A request carries a stable observation ID, stable plant-record key, optional taxon, observation timestamp and location, response type/label, observation text, confidence, environmental/cultivation/treatment/Matrix context, canonical source/revision/extraction identifiers, and exact source anchors.

## Scientific semantics

The graph preview uses:

`plant --observed_as--> phenotype/symptom/physiology/trait/developmental_process`

`observed_as` is controlled evidence semantics with role `evidence`, polarity `0`, and `causal=false`. Raw local observations never use a causal predicate.

## Candidate Knowledge behavior

Each event enters Candidate Knowledge as `CULTIVATION_OBSERVATION`, not `MECHANISTIC_RELATIONSHIP`.

The normalized candidate subject includes plant-record key and observation ID so repeated observations form a longitudinal event series rather than superseding one another as conflicting versions of one claim.

Every local observation remains review required, `published=false`, local only, non-generalizable, non-causal, and outside the mechanistic publication planner.

## Scope

Every observation receives a BUILD-618 bounded applicability scope containing available taxon, environmental context, treatment context, cultivation context, exact plant record, observation time, location, and population context with `n=1`.

The applicability note explicitly states that a single-plant cultivation event cannot be generalized without independent evidence.

## Read contract

Protected endpoint:

`GET /api/platform/matrix/plants/{plant_record_key}/observations`

This returns active local observations chronologically as local reasoning context. The response explicitly states `reasoning_use=local_context_only`, `species_level_generalization=false`, `canonical_graph_mutated=false`, and `scientific_publication_authority=false`.

## Governance interaction

The BUILD-616 publication planner rejects local-observation candidates because their kind is `CULTIVATION_OBSERVATION`, preventing a reviewed local event from becoming a canonical mechanistic publication plan.

Future aggregation of many observations must remain a separate governed operation requiring independent evidence and scientific review.

## Validation

Focused regressions verify non-causal Candidate Knowledge semantics, evidence-only graph preview, distinct longitudinal events, no false Candidate Knowledge conflicts, rejection by the mechanistic publication planner, scope binding to plant/taxon/time/location/`n=1`, local-history behavior, and absence of canonical graph or publication authority.

The dedicated workflow runs BUILD-620 plus BUILD-619/618 regressions, route verification, compile, Ruff lint/format, and repository hygiene.

## Governance boundary

BUILD-620-R2 does not authorize scientific publication, canonical Knowledge Graph mutation, taxonomy activation, deployment, production database mutation, contradiction resolution, or species-level generalization.
