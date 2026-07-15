# BUILD-066 — Domain Coverage Report

Backbone taxa: **33,786**. "Taxa connected" = distinct canonical taxa that gain
≥1 edge in this domain.

| Domain | Taxa connected | Backbone coverage | Edges | Confidence | Readiness |
|---|---|---|---|---|---|
| climate | 19,263 | 57.01 % | 19,263 | low | BLOCKED (occurrence-derived proxy, not bioclim) |
| traits | 2,296 | 6.80 % | 2,807 | medium | READY w/ operator review |
| mycorrhiza | 306 | 0.91 % | 626 | medium | PARTIALLY READY (name-join fan-out) |
| media | 20 | 0.059 % | 51 | high | READY |
| occurrences | 20 | 0.059 % | 26 | high | READY w/ review (curated subset only) |
| literature | 15 | 0.044 % | 29 | medium | PARTIALLY READY |
| pollinators | 4 | 0.012 % | 23 | high | READY w/ review |
| conservation | 2 | 0.006 % | 2 | high | PARTIALLY READY (source genuinely sparse) |

## Interpretation
- Coverage is **real but uneven**. Excluding the climate proxy, the
  scientifically-firm domains (traits, media, occurrences, pollinators,
  conservation, literature, mycorrhiza) connect ~2,300 distinct taxa.
- `traits` is the strongest defensible domain (6.8 % of the backbone via a
  resolved consensus view, id-anchored, no name matching).
- `conservation` and `pollinators` are tiny because the **production source is
  genuinely sparse**, not because of restrictive SQL (verified 2026-07-15).
- Every domain populated independently.
