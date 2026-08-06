# Priority Implementation Batch — ATLAS-401 through MC-201

Status: candidate implementation; not production activated.

## Implemented slices

1. BUILD-ATLAS-401 — durable spatial layer identities, CRS, provenance, license, checksum, idempotent registration.
2. BUILD-ATLAS-402 — provider-neutral Earth Systems adapter with supported-variable validation and normalized candidate datasets.
3. BUILD-ATLAS-403 — deterministic thematic-map artifact assembly requiring biodiversity, Earth-science, conservation, and sampling layers.
4. BUILD-RS-500 — evidence-preserving research workspace with hypotheses, evidence, candidate conclusions, and publication disabled.
5. BUILD-CON-600 — specimen records with accession, taxon, location, provenance, stable QR payload, and printable label text.
6. BUILD-MATRIX-700 — character-state contracts and explainable comparison with matches, differences, and missing-data accounting.
7. BUILD-VISION-800 — governed visual observations with regions, proposed characters, confidence, and candidate/reviewed/rejected states.
8. BUILD-PUB-900 — evidence-linked publication packages that remain unpublished even when review status is approved.
9. BUILD-INT-950 — deterministic cross-system event envelopes with payload checksums and candidate-only status.
10. BUILD-MC-201 — deterministic cross-system readiness projection with dependency-based blocker reporting.

## Safety boundary

No production database migration, dataset harvesting, map publication, specimen write API, scientific conclusion publication, external event delivery, deployment, merge, or production Knowledge Graph mutation is enabled.

## Validation

Focused tests cover deterministic map rendering, unsupported Earth variables, candidate research status, QR/label stability, Matrix missing-data handling, visual-review gating, publication disablement, deterministic event IDs, and readiness projection.
