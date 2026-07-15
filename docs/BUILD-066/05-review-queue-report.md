# BUILD-066 — Review Queue Report

Records/decisions routed to a human, never discarded. Detail:
`review_queue_report.json` (+ BUILD-065 `Taxonomic_Conflict_Report.xlsx`).

## Taxonomic conflict queues (from canonical backbone)
| Queue | Items |
|---|---|
| Unresolved synonym chains (synonym → synonym) | 376 |
| Authority disagreements (same authority, ≥2 external ids on one taxon) | 323 |
| Duplicate accepted taxa (same canonical name accepted twice) | 0 |
| **Total taxonomic** | **699** |

## Domain connectivity review items
| Item | Detail |
|---|---|
| **climate = proxy, not bioclim** | 19,263 edges from occurrence-derived proxy; withhold or publish with explicit proxy provenance. |
| **mycorrhiza name collisions** | 32 names fan out to >1 taxon (462→626 edges); verify before publish. |
| occurrences source selection | Choose bulk vs curated occurrence source before controlled population. |
| literature id gap | name_join only; awaits upstream taxon id for crosswalk. |

No record in any queue is deleted; each stays in its source pending resolution.
