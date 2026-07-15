# BUILD-064 Deliverable 8 — Name Collision Statistics

Source: `docs/crosswalks/name_collision_statistics.json`. Generated 2026-07-15.
Measures the current domain-level name join (`domain.name → kg_nodes.display_label`).

| Domain | Src rows | Distinct names | Matched | Orphans | Colliding names (>1 node) | Edges after join (fan-out) | Match rate | Orphan rate | Collision rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pollinators | 23 | 4 | 4 | 0 | 0 | 23 | 1.0 | 0.0 | 0.0 |
| mycorrhiza | 462 | 218 | 122 | 96 | 32 | 626 | 0.56 | 0.44 | 0.262 |
| literature | 35 | 20 | 15 | 5 | 0 | 29 | 0.75 | 0.25 | 0.0 |

- Backbone display_labels appearing more than once (collision source): **466**.

## Interpretation
- **pollinators** — clean (4/4 matched, 0 orphan, 0 collision) but tiny.
- **mycorrhiza** — 44% orphan names and 32 colliding names inflate 462 source
  rows to 626 edges. Highest ambiguity; needs crosswalk/operator review.
- **literature** — 25% orphan, no collision; unmatched rows drop (35 → 29).
