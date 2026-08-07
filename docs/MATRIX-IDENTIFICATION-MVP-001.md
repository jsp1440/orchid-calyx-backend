# MATRIX-IDENTIFICATION-MVP-001 — Governed Character Matching

## Completed

- Added a deterministic weighted character-matrix engine.
- Added explicit certainty states: `certain`, `probable`, `uncertain`, and `unknown`.
- Added scalar, multi-state, numeric, and numeric-range matching.
- Added per-character explanations, contributions, conflicts, and missing-state notices.
- Added separate score and coverage measures.
- Added deterministic tie-breaking.
- Added an owner-gated API and CORS registration.
- Added focused tests and CI.

## API

- `GET /api/matrix-identification/contract`
- `POST /api/matrix-identification/evaluate`

The caller supplies observations and a governed candidate matrix. The engine ranks those candidates only. It does not invent a candidate universe.

## Governance

- Results are candidate-ranking evidence, not a taxonomic determination.
- Unknown observations contribute no score.
- Missing candidate states reduce coverage and are not treated as biological absence.
- Uncertain observations receive lower effective weight.
- Every result preserves character-level explanations and optional candidate provenance.
- No canonical taxonomy, collection record, or graph relationship is changed.

## Brain record

Decision: begin the Matrix Identification system with a small, auditable scoring kernel before adding image suggestions, interactive keys, or automated candidate retrieval. Candidate retrieval must later come from governed canonical taxa and evidence-backed character assertions. The engine must remain explainable and must never convert absence of evidence into evidence of absence.

## Next integration slices

1. Matrix dataset registry with versioning and provenance.
2. Canonical taxon candidate retrieval by genus or clade.
3. Conservatory plant observation records linked to stable plant IDs.
4. Frontend identification worksheet and candidate explanation view.
5. Image-derived observations stored as suggestions requiring review.
