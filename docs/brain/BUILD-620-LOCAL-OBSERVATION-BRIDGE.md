# BUILD-620 — Matrix / Conservatory Local Observation Bridge

## Status

Implemented on `feature/build-620-local-observation-bridge`, stacked on BUILD-619. This build must not merge before the BUILD-615→619 prerequisite stack is validation-cleared and GitHub Actions hosted-runner issue #481 is resolved.

## Purpose

BUILD-620 lets Matrix / Conservatory submit real plant responses into Candidate Knowledge as local evidence without converting a single plant event into a species-wide or canonical causal claim.

The bridge supports the longitudinal workflow:

`plant record → observation event → exact evidence → bounded local scope → Candidate Knowledge → local reasoning context`

It deliberately does **not** perform:

`plant observation → species mechanism`

## Write contract

Protected endpoint:

`POST /api/platform/matrix/local-observation`

A request carries:

- stable observation identifier;
- stable plant-record key;
- optional taxon identity;
- observation timestamp and location key;
- response type and response label;
- observation text;
- confidence;
- environmental, cultivation, treatment, and Matrix context;
- canonical source/revision/extraction identifiers;
- exact source anchors.

## Scientific semantics

The graph preview uses:

`plant --observed_as--> phenotype/symptom/physiology/trait/developmental_process`

`observed_as` is a controlled evidence relationship with:

- role: `evidence`;
- polarity: `0`;
- causal: `false`.

The bridge never uses `causes`, `promotes`, `inhibits`, or another causal predicate for the raw plant observation.

## Candidate Knowledge behavior

Each event enters Candidate Knowledge as `CULTIVATION_OBSERVATION`, not `MECHANISTIC_RELATIONSHIP`.

The normalized candidate subject includes both the plant-record key and observation ID. This is intentional: repeated observations of the same plant form a longitudinal event series instead of superseding one another as conflicting versions of a single claim.

Every local observation remains:

- review required;
- `published=false`;
- local only;
- non-generalizable;
- non-causal;
- outside the mechanistic publication planner.

## Scope

Every observation receives a BUILD-618 bounded causal/applicability scope containing, when available:

- taxon;
- environmental context;
- treatment context;
- cultivation context;
- exact plant record;
- exact observation time;
- location key;
- population context with `n=1`.

The applicability note explicitly states that the observation is a single-plant cultivation event and cannot be generalized without independent evidence.

## Read contract

Protected endpoint:

`GET /api/platform/matrix/plants/{plant_record_key}/observations`

This returns active local observations for the specified plant as a chronological local-context artifact suitable for Matrix/Calyx diagnostic use.

The response explicitly states:

- `reasoning_use = local_context_only`;
- `species_level_generalization = false`;
- `canonical_graph_mutated = false`;
- `scientific_publication_authority = false`.

## Governance interaction

The existing BUILD-616 mechanistic publication planner rejects these candidates because their kind is `CULTIVATION_OBSERVATION` rather than `MECHANISTIC_RELATIONSHIP`.

Therefore human review of a local observation cannot accidentally make it publication-ready as a canonical mechanism.

A future aggregation build may compare many independent local observations and propose a research hypothesis, but such aggregation must remain a separate governed operation requiring independent evidence and scientific review.

## Validation

`tests/test_build_620_local_observation_bridge.py` verifies:

- local observations are non-causal Candidate Knowledge;
- graph preview semantics are evidence-only;
- repeated same-plant events remain distinct and active;
- repeated events do not create false Candidate Knowledge conflicts;
- local observations are rejected by the mechanistic publication planner;
- scope binds evidence to plant, taxon, time, location, and `n=1`;
- local history returns only bounded local context;
- no canonical graph write or publication authority is created.

The dedicated BUILD-620 workflow also runs relevant BUILD-618/619 scope regressions, route import checks, Ruff, formatting, compile, and hygiene.

## Next dependency

After executable CI is restored, the next high-value integration is a read-only **plant diagnostic context composer** that combines:

1. canonical scoped reasoning-map pathways;
2. the plant's local observation history;
3. environmental/cultivation state;
4. explicit separation between canonical mechanisms, hypotheses, and local observations.

That composer must not infer a new canonical mechanism merely because a local observation resembles a published pathway.
