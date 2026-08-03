# OC-MATRIX-KG-003

## Mission

Connect the merged Matrix evidence-adapter foundation to bounded canonical Knowledge Graph and PostgreSQL retrieval, then expose explainable neighborhood discovery.

## Implementation sequence

1. Add read-only repository protocols for canonical taxon identity, graph edges, occurrences, literature, traits, pollinators, mycorrhizae, conservation, and cultivation evidence.
2. Hydrate all eleven Matrix dimensions with availability, evidence, confidence, provenance, freshness, and limitations.
3. Add bounded nearest-neighbor candidate retrieval with deterministic ordering, pagination, and filters.
4. Add relationship-path explanations that distinguish direct evidence from inferred paths.
5. Expose versioned pairwise and neighborhood routes under `/api/platform/matrix`.
6. Add deterministic fixtures, database-degraded behavior, and focused/regression CI.

## Governance

Read-only retrieval only. Missing evidence remains unavailable. No graph writes, scientific publication, taxonomy promotion, or verified identity decisions.

## Completion

Pairwise and neighborhood requests return canonical, explainable evidence envelopes and fail safely when one or more source repositories are unavailable.
