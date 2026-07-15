# BUILD-065 — Crosswalk Maintenance Guide

## Sources reused (from BUILD-064)
`docs/crosswalks/orchid_taxonomy_to_backbone_crosswalk.csv` — 10,409 pairs
(`orchid_taxonomy.id → taxonomy_species.id`) via
`oc_taxonomy.taxon_crosswalk` (10,070 exact id↔id) + a final canonical-name hop.

## Classification (this build)
| Class | Count | Auto-publishable |
| --- | ---: | :---: |
| exact_id | 0 | yes |
| authority_supported_synonym | 0 | yes |
| **accepted_name_mapping** | **10,409** | yes |
| historical_mapping | 0 | no |
| manual_review_required | 0 | no |

Every one of the 10,409 mappings is an id-anchored **accepted-name mapping**
(method `crosswalk_id+canonical_name`, confidence 1.0, authoritative crosswalk
provenance) — auto-publishable. None are fuzzy.

## Rules
- Every mapping must retain `confidence`, `authority`, `source`, `provenance`,
  `quality_score` (all present in the CSV).
- `classify_mapping()` is the single source of truth for publishability.
- Re-classify after any crosswalk regeneration; a mapping that drops below its
  confidence threshold falls to `manual_review_required` and must not publish.
