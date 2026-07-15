# BUILD-066 — Graph Completeness Report

Per-taxon connectivity across all 8 domains (projected DRY_RUN). Full per-taxon
detail: `graph_completeness_per_taxon.csv`.

## Aggregate
| Metric | Value |
|---|---|
| Canonical taxa in backbone | 33,786 |
| Taxa connected to ≥1 domain | 20,038 |
| Taxa fully unconnected | 13,748 |
| **Overall completion** | **59.31 %** |

## Distribution — domains connected per taxon
| Domains connected | Taxa |
|---|---|
| 0 | 13,748 |
| 1 | 18,252 |
| 2 | 1,684 |
| 3 | 102 |

## Reading the number
- The 59.31 % figure is **driven mostly by the climate proxy** (57 % of taxa
  gain only the climate edge). If climate is withheld from publish, overall
  completion by the firm domains is ~7 % of the backbone — an honest baseline
  reflecting genuine production data availability, not a pipeline limitation.
- The 13,748 fully-unconnected taxa have **no defensible domain record in any
  production source today**; they are documented, not discarded, and will
  connect automatically as sources are populated (re-run is idempotent).
