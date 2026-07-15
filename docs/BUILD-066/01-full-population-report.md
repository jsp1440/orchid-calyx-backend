# BUILD-066 — Full Graph Population Report (DRY_RUN, projected)

Mode `DRY_RUN` · `wrote_to_production=False` · staging graph seeded read-only
from the production `taxon`/`genus` backbone. Counts = what an authorized
`PUBLISH` would write.

## Totals
| Metric | Value |
|---|---|
| Nodes projected | 22,492 |
| Edges projected | 22,827 |
| Rows processed | 22,827 |
| Invalid rows rejected | 0 |
| Skipped (already present) | 0 (empty staging) |
| Orphan edges (endpoint unresolved) | 0 |

## Per-domain projection (pipeline order)
| Domain | Rows connected | Nodes | Edges | Strategy | Readiness |
|---|---|---|---|---|---|
| occurrences | 26 | 26 | 26 | direct | READY w/ review |
| traits | 2,807 | 2,807 | 2,807 | resolved_view | READY w/ review |
| pollinators | 23 | 23 | 23 | name_join | READY w/ review |
| mycorrhiza | 626 | 626 | 626 | name_join | PARTIALLY READY |
| conservation | 2 | 2 | 2 | direct | PARTIALLY READY |
| climate | 19,263 | 19,263 | 19,263 | direct | **BLOCKED (proxy)** |
| literature | 29 | 29 | 29 | name_join | PARTIALLY READY |
| media | 51 | 51 | 51 | direct | READY |

## Cross-domain validation
- Invalid node/edge types: 0
- Orphan edges: 0 (every edge resolves to a backbone taxon)
- Orphan nodes: 14,481 — a **staging artifact**: the staging graph seeds
  `taxon`/`genus` nodes but not the taxonomy `genus_contains_species` edges, so
  backbone taxa carrying no domain edge appear edge-less. In production the
  taxonomy edges already exist, so this does not represent a real defect.

## Independence
Each domain ran independently; no domain's gap blocked another. All 8 completed.
