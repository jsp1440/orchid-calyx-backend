# BUILD-620-R3 — Governed local observation bridge on canonical BUILD-619

## Status

IMPLEMENTED / EXACT-HEAD VALIDATION REQUIRED.

This reconstruction starts directly from canonical main after BUILD-619-R3 merged as `6aff70a2b2fe75fd0be4311431ffd04a3c2df3b1`. Historical BUILD-620-R2 PR #789 remains behavioral source material only until this current-parent reconstruction is validated and merged.

## Contract

A Matrix / Conservatory single-plant event enters Candidate Knowledge as `CULTIVATION_OBSERVATION` with exact evidence anchors and a bounded canonical BUILD-618 applicability scope tied to the plant, taxon, time, location, environment, treatment, cultivation context, and `n=1` population context.

The preview relation remains controlled `observed_as` evidence semantics with `causal=false` and polarity `0`. Repeated observations use distinct observation identity so they form longitudinal local history rather than superseding one another.

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

The dedicated BUILD-620 gate compiles, lints, format-checks, and tests local observation surfaces; runs canonical BUILD-619 and BUILD-618 prerequisite regressions; verifies both protected Matrix routes; and checks hygiene. Applicable Candidate Knowledge, publication-control, Workflow Governance, Calyx Brain Integration, Brain E2E, and platform route checks must pass on the unchanged exact head before merge.

## Child dependency

After BUILD-620-R3 is canonical, BUILD-621-R2 must be synchronized/reconstructed directly on the BUILD-620 merge and fully revalidated. The previous #790 head `7f5bfd4d...` remains historical validation only after its parent changes.
