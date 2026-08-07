# MATRIX-RELATIONSHIP-MVP-001

## Objective

Provide a governed, read-only relationship matrix that can compare taxa or Conservatory plants across parentage, morphology, pollinators, mycorrhizal partners, habitat, climate, geography, literature and collection-to-taxon links.

## Completed work

- Added deterministic matrix projection from supplied evidence assertions.
- Preserved `present`, `absent`, `unknown`, `not_recorded` and `conflicting` as separate epistemic states.
- Added conflict collapse when present and absent assertions coexist.
- Preserved assertion count, mean confidence and provenance in every populated cell.
- Added deterministic subject and object ordering.
- Added row-to-row comparison with shared-present and present-versus-absent disagreement counts.
- Added owner-gated contract, build and compare endpoints.
- Added CORS integration, focused tests and CI.

## API

- `GET /api/matrix-relationship/contract`
- `POST /api/matrix-relationship/build`
- `POST /api/matrix-relationship/compare`

## Governance

This implementation is read-only. It does not mutate the canonical taxonomy, knowledge graph, Conservatory records or source assertions. A missing assertion is represented as `not_recorded`; it is never interpreted as biological absence. Conflicting evidence remains visible and is not silently resolved.

## Next integration work

1. Load versioned assertions from governed graph and literature sources.
2. Link Conservatory plant IDs to canonical taxon IDs without overwriting entered names.
3. Add frontend matrix controls, filters and provenance inspection.
4. Add export formats and saved matrix definitions.
5. Add evidence-review workflows before any assertion can enter a published matrix registry.
