# BUILD-620-R4 — Governed local observation bridge on current canonical main

## Status

IMPLEMENTED / EXACT-HEAD VALIDATION REQUIRED.

This reconstruction starts directly from canonical `main` after BUILD-619-R3 and the subsequent non-overlapping canonical release-record update. BUILD-620-R3 PR #807 demonstrated the corrected behavior and full integration suite, but its ancestry shape is not an authorized merge path through the available repository merge controls. Historical BUILD-620-R2 PR #789 remains source material only.

## Contract

A Matrix / Conservatory single-plant event enters Candidate Knowledge as `CULTIVATION_OBSERVATION` with exact evidence anchors and a bounded canonical BUILD-618 applicability scope tied to the plant, taxon, time, location, environment, treatment, cultivation context, and `n=1` population context.

The preview relation remains controlled `observed_as` evidence semantics with `causal=false` and polarity `0`. Repeated observations use distinct observation identity so they form longitudinal local history rather than superseding one another.

`observation_id` and `plant_record_key` are normalized before identity construction and semantically blank identifiers are rejected. This prevents a formally bounded local observation from losing its actual plant identity during canonical applicability normalization.

The protected history endpoint returns local plant context only. The canonical mechanistic publication planner rejects `CULTIVATION_OBSERVATION` candidates by kind, so scientific review cannot accidentally turn one plant observation into a canonical mechanistic relationship.

## Scientific / knowledge boundaries

- local observations remain review-required and `published=false`;
- local observations are non-generalizable and do not alter canonical reasoning confidence;
- no local observation automatically becomes mechanistic Candidate Knowledge;
- Candidate Knowledge duplicate identity remains owned by the canonical Candidate Knowledge service;
- no alternate provenance representation is introduced;
- no canonical Knowledge Graph mutation, scientific publication, contradiction resolution, production DB mutation, taxonomy activation, or deployment occurs.

## API

Protected Matrix routes:

- `POST /api/platform/matrix/local-observation`
- `GET /api/platform/matrix/plants/{plant_record_key}/observations`

## Validation

R4 requires a completely fresh exact-head release gate. The dedicated BUILD-620 workflow compiles, lints, format-checks, and tests local-observation surfaces; runs canonical BUILD-619 and BUILD-618 prerequisite regressions; verifies both protected Matrix routes; and checks hygiene. Applicable Candidate Knowledge, publication-control, Workflow Governance, Calyx Brain Integration, Brain E2E, and platform route checks must all pass on the unchanged R4 head before merge. The green #807 runs are evidence only and are not reused as R4 release authority.

## Child dependency

Only after BUILD-620-R4 is canonical may BUILD-621 be reconstructed directly on its merge and fully revalidated. Historical PR #790 and its previous green validation cannot be promoted across the new parent.
