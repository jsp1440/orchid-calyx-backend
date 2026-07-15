# BUILD-068 — Controlled Production Population of the Scientific Knowledge Graph

**Verdict: COMPLETED**

Owner-authorized, controlled production write of six scientific domains into the
production knowledge graph tables `oc_graph.kg_nodes` / `oc_graph.kg_edges`,
using the BUILD-067 `WritablePostgresGraphRepository`.

- Repository: `jsp1440/orchid-calyx-backend`
- Branch: `feat/scientific-knowledge-graph-completion` (PR #56 — NOT merged)
- Build run id: `1784124130`
- Canonical authority: `world_plants` (Hassler / World Plants)

## Domains published (authorized)
media, traits, pollinators, occurrences, literature, conservation

## Domains WITHHELD (never written)
climate, mycorrhiza — never supplied to the publisher; verified absent post-write
(`climate_edges_present=0`, `mycorrhiza_edges_present=0`).

## Result summary
| metric | value |
|---|---|
| baseline nodes / edges | 34519 / 67572 |
| final nodes / edges | 37457 / 70510 |
| nodes added / edges added | +2938 / +2938 |
| all domains done | True |
| any domain failed | False |

## Nodes added by node_type
- trait: 2807
- image: 51
- publication: 29
- occurrence: 26
- pollinator: 23
- conservation_assessment: 2

## Edges added by edge_type
- has_trait: 2807
- has_image: 51
- documented_by: 29
- occurs_at: 26
- associated_with_pollinator: 23
- has_conservation_assessment: 2

## Edges added by source_table
- oc_views.trait_resolved_v4: 2807
- oc_api.species_media_gallery_v1: 51
- oc_graph.taxon_literature_edges: 29
- oc_atlas.occurrences: 26
- oc_interactions.orchid_interaction_edges: 23
- oc_conservation.conservation_records: 2

## Post-publish validation (full-graph)
- healthy: **True**
- total problems: 0
- orphan nodes / edges: 0 / 0
- duplicate relationships: {'duplicate_edges': 0}
- identifier integrity: {'invalid_canonical_keys': 0, 'examples': []}
- provenance completeness: {'nodes_missing_provenance': 0, 'edges_missing_provenance': 0}
- vocabulary compliant: True
- cross-domain consistency: {'mismatched_endpoint_edges': 0, 'examples': []}

## Connectivity to canonical taxonomy
- canonical taxa total: 34519
- canonical taxa connected to a newly-authorized domain edge: 2332

Every new domain node is attached to a canonical `world_plants` taxon via its
domain edge (`has_trait`, `has_image`, `documented_by`, `occurs_at`,
`associated_with_pollinator`, `has_conservation_assessment`). Post-publish
validation reports **0 orphan nodes and 0 orphan edges**, confirming full
attachment.

## Idempotency (zero-inflation rerun)
Re-running all six domains against the populated graph:
- node delta: 0
- edge delta: 0
- no inflation: **True**
- duration: 25.6s (all rows skipped in-memory)

## Publish execution model
Publish ran in 2 resumable execution window(s). See
`RUNBOOK.md` for the transaction / checkpoint / resume design and rationale.
