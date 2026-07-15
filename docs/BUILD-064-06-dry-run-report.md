# BUILD-064 Deliverable 6 — DRY_RUN Report

Mode: DRY_RUN (full projection into a staging graph). Verification: 2026-07-15.
`wrote_to_production`: **False** — zero production writes.

## Totals
- nodes_written: 22492
- edges_written: 22827
- rows_processed: 22827
- invalid: 0

## Per domain
| Domain | Available | Processed | Nodes | Edges | Invalid |
| --- | ---: | ---: | ---: | ---: | ---: |
| occurrences | 26 | 26 | 26 | 26 | 0 |
| traits | 2807 | 2807 | 2807 | 2807 | 0 |
| pollinators | 23 | 23 | 23 | 23 | 0 |
| mycorrhiza | 626 | 626 | 291 | 626 | 0 |
| conservation | 2 | 2 | 2 | 2 | 0 |
| climate | 19263 | 19263 | 19263 | 19263 | 0 |
| literature | 29 | 29 | 29 | 29 | 0 |
| media | 51 | 51 | 51 | 51 | 0 |

## Cross-domain validation
- identifier_integrity.invalid_canonical_keys: 0
- duplicate_relationships.duplicate_edges: 0
- orphan_edges: 0
- vocabulary_compliance.compliant: True
- provenance_completeness: {'nodes_missing_provenance': 0, 'edges_missing_provenance': 0}
- **orphan_nodes: 14481** — backbone taxa with no domain edge yet (coverage sparsity, expected; not a defect)

Identity, edge, provenance and vocabulary checks are all clean/zero. Graph
health is limited only by coverage sparsity, driven by the small connected
source volumes documented in Deliverables 2–3.
