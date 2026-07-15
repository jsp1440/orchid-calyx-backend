# BUILD-066 — Unconnected Records Report

Records present in a domain's real source but **not** connected to the backbone.
Nothing is discarded — every gap has a documented reason. Machine-readable:
`unconnected_records_report.json`.

| Domain | Source candidates | Connected | Unconnected / orphaned | Reason |
|---|---|---|---|---|
| occurrences | ~580,000 | 26 | ~579,974 | Bulk `public.orchid_occurrence` (580,612) + `public.oc_occurrences` (114,517) link via ambiguous ids (unverified taxon linkage). Only the 26 curated `oc_atlas.occurrences` rows are safely connectable. Decide source before controlled population. |
| traits | 33,791 | 2,807 | 30,984 | Remaining taxa simply lack resolved trait-consensus rows (source gap, not a mapping failure). |
| literature | 35 | 29 | 6 | 5 orphan names + drop; source carries no taxon id (name_join only) — crosswalk needs an upstream extractor id. |
| mycorrhiza | 462 | 626 (fan-out) | 96 orphan names | 96 of 218 names unresolved; 32 names collide → 462 rows inflate to 626 edges. Crosswalk upgrade recommended. |
| pollinators | 23 | 23 | 0 | Clean (4 names, all resolve). |
| conservation | 2 | 2 | 0 | Source genuinely sparse (CITES/IUCN tables empty/null). |
| media | 51 | 51 | 0 | Clean direct-id join. |
| climate | 19,263 | 19,263 | 0 | Connected, but **proxy** — see review queue / completion report. |

All unconnected populations remain in their source tables and will attach on a
future idempotent re-run once linkage/crosswalk/source issues are resolved.
