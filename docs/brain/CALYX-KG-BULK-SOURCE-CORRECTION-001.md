# CALYX-KG-BULK-SOURCE-CORRECTION-001

## Production evidence

Read-only Render-shell inspection on 2026-08-12 established that the deployed database contains substantially larger scientific corpora than the legacy graph source registry selected:

- `public.orchid_occurrence`: 580,612 rows
- `public.orchid_occurrence_filtered`: 71,565 rows
- `public.records`: 5,006,022 rows
- `public.oc_trait_consensus`: 19,929 rows
- `public.oc_trait_consensus_normalized`: 19,929 rows
- `public.research_documents`: 6,725 rows
- `public.oc_species_habitat_claims`: 695 rows

The persisted graph baseline contained only 26 occurrence nodes/edges, 2,807 trait nodes, and 29 publication nodes. Presence of an edge type therefore cannot be used as evidence of corpus-complete integration.

## Implemented correction

`runtime/knowledge_graph/verified_bulk_sources.py` now provides reviewed SELECT-only bulk projections for the two source contracts whose live schema and taxon crosswalk were established directly from production catalog inspection:

1. **Occurrences** use `public.orchid_occurrence`, keyed by `occurrence_id` and linked through `taxonomy_id`. The projection preserves scientific name, country, region, locality, decimal latitude/longitude, point/min/max elevation, growth habit, habitat description, climate/temperature/humidity fields, source relation, source record identifier, raw payload, and timestamps.
2. **Traits** use `public.oc_trait_consensus_normalized`, linked by `coalesce(accepted_taxon_id, taxon_id)`. The projection preserves normalized trait name, source trait value, normalized unit, confidence/final score, vocabulary status, source relation/key, source scientific name, taxonomy match metadata, source weight, and vocabulary-normalization method.

Both projections require the target taxonomy identifier to resolve to an existing persisted `oc_graph` taxon node and are validated by the same SELECT-only SQL guard used by the canonical source registry.

`production_materializer.py` now overlays these verified bulk projections over the legacy registry for `occurrences` and `traits`. Both bounded dry-run and authorized transactional publication therefore use the same corrected source map. Production publication also now passes the selected reviewed query map explicitly to `publish_to_production`; it cannot silently fall back to the legacy 26-row occurrence source during execution.

`adapters.py` records the corrected source-table provenance and preserves the expanded occurrence and trait evidence payloads.

## Governance

No production graph mutation was performed by this implementation pass. Production materialization remains gated by an explicit domain list, `execute=True`, and exact confirmation token `PUBLISH_VERIFIED_GRAPH_RELATIONSHIPS`, and remains owner-governed.

## Validation

Added `tests/test_verified_bulk_graph_sources.py` to assert:

- both bulk queries remain SELECT-only;
- occurrence materialization selects `public.orchid_occurrence` rather than `oc_atlas.occurrences`;
- trait materialization selects `public.oc_trait_consensus_normalized` rather than `oc_views.trait_resolved_v4`;
- coordinate/elevation fields and taxon crosswalks remain in the occurrence projection;
- normalized trait identity/value and accepted-taxonomy crosswalk remain in the trait projection;
- graph adapter provenance names the corrected live source relations.

A dedicated exact-head workflow `.github/workflows/calyx-kg-bulk-source-validation.yml` compiles the integration, runs focused and adjacent source/materializer regressions, runs Ruff, and checks diff hygiene. A GitHub-hosted job must execute real steps before it counts as validation evidence.

## Next highest-priority work

1. Obtain executable validation for the exact branch head.
2. Run bounded read-only dry-runs against production for `occurrences` and `traits`, measuring rows resolved to canonical taxon nodes and staging idempotency.
3. Add source-coverage readiness thresholds so 26/580,612 can never be reported as integrated.
4. Verify the taxon-link path from `public.research_documents` and literature extraction objects before replacing the 35-edge/29-node literature path.
5. Verify habitat/elevation projections from the live `oc_species_habitat_claims`, occurrence evidence, and taxon elevation profile tables without conflating raw observations with derived profiles.
6. Only after owner authorization, publish one validated domain at a time and re-run persisted graph audit after each transaction.
