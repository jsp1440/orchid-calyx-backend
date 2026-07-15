# BUILD-065 — Validation & Owner Safety Checkpoint

Read-only build. All figures verified 2026-07-15 against production. **No
production writes occurred in any mode.**

## Validation results (AUDIT → DRY_RUN → LIMITED_POPULATION)
| Mode | Wrote to prod | Nodes | Edges | Invalid | Orphan edges |
| --- | :---: | ---: | ---: | ---: | ---: |
| AUDIT | No | 0 | 0 | 0 | n/a |
| DRY_RUN (all domains) | No | 22,492 | 22,827 | 0 | 0 |
| LIMITED_POPULATION (activated only) | **No** | 2,907 | 2,907 | 0 | 0 |

- **Zero invalid rows** and **zero orphan edges** in every mode — no dangling
  evidence would be produced.
- Orphan *nodes* (backbone taxa with no domain edge) are expected coverage
  sparsity, not corruption; they carry no dangling relationships.
- LIMITED_POPULATION activates exactly `media, occurrences, pollinators,
  traits`; `climate, conservation, mycorrhiza, literature` report
  `status="skipped"` (withheld).

## Owner safety checkpoint (numbers to approve)
| Item | Value |
| --- | ---: |
| Canonical authority | World Plants (Dr. Michael Hassler) |
| Canonical release | `2026-02` (`f8638e1d`), 1 superseded duplicate |
| Canonical taxa | 73,661 (31,727 accepted · 41,934 synonyms · 127 hybrids) |
| Authority mappings | 46,782 (GBIF 46,012 · POWO 770) |
| Crosswalk mappings | 10,409 — all accepted-name, auto-publishable, 0 fuzzy |
| Conflicts to review | 376 synonym chains · 323 authority disagreements |
| Projected LIMITED population | 2,907 nodes · 2,907 edges (4 domains) |
| Tests | 89 pass (25 new), no production writes |

## Required before broader (CONTROLLED) population
1. Owner resolves the 376 unresolved synonym chains and 323 authority
   disagreements (`Taxonomic_Conflict_Report.xlsx`).
2. Withheld domains stay disabled until their blocking data gaps are fixed.
3. Explicit owner authorization (`authorized_to_publish=True`, `PUBLISH`) before
   any real write.
