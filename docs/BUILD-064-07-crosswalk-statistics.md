# BUILD-064 Deliverable 7 — Crosswalk Statistics

Source data: `docs/crosswalks/orchid_taxonomy_to_backbone_crosswalk.csv`
and `crosswalk_statistics.json`. Generated 2026-07-15 (read-only).

## Reusable crosswalk: `orchid_taxonomy.id → taxonomy_species.id`
- total mapped pairs: 10409
- distinct source ids: 9778
- distinct destination ids: 10390
- source ids with fan-out >1 (one orchid id → several backbone taxa): 271
- destination ids with fan-in >1: 19

Method: `orchid_taxonomy_id → oc_taxonomy.taxon_crosswalk (id↔id, exact_match,
conf 1.0) → oc_taxonomy.taxa → canonical-name equality → backbone`. Each row
carries method, confidence, authority, date, provenance and a quality_score.

## Underlying id crosswalk (`oc_taxonomy.taxon_crosswalk`)
- rows: 10070 (all 10070 `exact_match`)
- distinct `orchid_taxonomy_id`: 10054

## External identifier coverage (context)
- `orchid_taxonomy_id` with a GBIF external id: 48175
- backbone taxa with a POWO authority link: 2837

The authority mismatch (orchid space → GBIF, backbone → POWO) is why no direct
shared-authority id bridge exists; see Deliverable 1.
