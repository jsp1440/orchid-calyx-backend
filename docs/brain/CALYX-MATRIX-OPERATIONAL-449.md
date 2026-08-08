# CALYX Matrix identification operational scoring — issue #449

Date: 2026-08-07
Status: bounded implementation delivered for deterministic validation; no definitive identification, taxonomy activation, publication, graph mutation, deployment, or merge performed.

## Integration posture

This build extends the existing canonical Matrix MVP rather than replacing it:

- `runtime/matrix_identification.py` remains the deterministic character scoring engine;
- `runtime/matrix_identification_registry.py` remains the immutable versioned character/candidate registry;
- `runtime/matrix_operational.py` adds durable identification sessions, replay identity, canonical/synonym resolution, explicit evidence accounting, confidence bounds, and explanation retrieval.

The existing registry already carries version, character metadata, candidate taxon identity, state profiles, provenance, checksum, and review-required publication state. Candidate provenance can retain reviewed literature/evidence references and synonyms without creating a second taxonomy store.

## Deterministic evidence accounting

Operational rankings decorate the canonical scorer output with explicit:

- support count/weight;
- contradiction count/weight;
- unknown-observation count/weight;
- candidate missing-data count/weight;
- lower and upper confidence bounds;
- per-character explanation records.

Unknown observations remain distinct from candidate missing data. Missing data are not biological absence. Partial similarity contributes both support and residual contradiction deterministically.

Ranking order remains deterministic through the existing score/coverage/name/taxon-ID ordering.

## Canonical identity and synonyms

The registry candidate `taxon_id` is treated as the canonical review-stage identity. Scientific name and provenance-carried synonyms resolve to that canonical ID. Ambiguous synonym ownership is surfaced rather than silently choosing a taxon.

No taxonomy activation or accepted-name mutation occurs.

## Saved sessions and replay

`create_identification_session()` binds:

- registry ID/version/checksum;
- ordered observations;
- certainty and observation weights;
- ranking limit.

The canonical payload is SHA-256 addressed. Identical input replays to the same session ID and stored record; conflicting immutable session content fails closed.

## Protected API

Owner/API-key-protected routes are exposed under:

`/brain/mission-control/matrix`

- `POST /sessions` — create/replay one bounded local identification session;
- `GET /sessions/{session_id}` — read ranking and evidence accounting;
- `GET /sessions/{session_id}/candidates/{canonical_taxon_id}` — read per-candidate/per-character explanation;
- `GET /registries/{registry_id}/{version}/resolve/{label}` — resolve canonical scientific name or synonym.

Ranking and explanation retrieval are read-only. Session creation writes only local review state; it has no taxonomy or Knowledge Graph authority.

## Orchid close-candidate fixture

Focused tests use `Cattleya labiata` and `Cattleya warneri` with lip color, flowers per inflorescence, pseudobulb shape, and fragrance. The fixture proves deterministic discrimination while retaining unknown and missing-data distinctions and never asserting a definitive identification.

## Governance

Every session permanently reports:

- `definitive_identification=false`;
- `human_review_required=true`;
- `taxonomy_activation_authorized=false`;
- `scientific_publication_authorized=false`;
- `knowledge_graph_mutation_authorized=false`.

## Validation

Dedicated workflow `.github/workflows/calyx-matrix-operational-449.yml` runs compile, new operational tests, existing Matrix MVP/registry regressions, governance assertions, Ruff, and `git diff --check`.

## Explicit non-actions

This slice does not autonomously identify a species, activate taxonomy, alter canonical taxonomy, publish scientific claims, mutate production graph data, deploy, or merge.
