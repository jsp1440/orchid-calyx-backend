# BUILD-064 Deliverable 3 — Source Completeness Report

Read-only. Verification: 2026-07-15. Explains the small occurrence and
conservation counts observed in BUILD-062.

## Occurrences — why only 26?
`oc_atlas.occurrences` genuinely contains **26 rows** (all 26 resolve cleanly to
the backbone). This is **not** a restrictive-SQL or permissions artifact — the
curated atlas table is nearly empty.

Bulk occurrence data lives in **alternate production tables**:
| Table | Rows | Backbone linkage |
| --- | ---: | --- |
| `public.orchid_occurrence` | 580,612 | `taxonomy_id` matches 52,935 rows; `accepted_taxon_id` resolves only **504** distinct backbone taxa |
| `public.oc_occurrences` | 114,517 | `species_id` resolves **0** backbone taxa |
| `public.orchid_occurrence_filtered` | 71,565 | 192 distinct backbone taxa |
| `oc_atlas.occurrences` (current source) | 26 | 20 taxa, all clean |

**Finding:** a wrong/curated-table situation. The rich tables exist but their
taxon linkage columns are **ambiguous** (`accepted_taxon_id` sparse;
`oc_occurrences.species_id` unusable against the backbone). Repointing was **not**
performed because the alt-source linkage is unverified; it is recorded as an
operator decision in the registry (`occurrences.operator_notes`).

## Conservation — why only 2?
`oc_conservation.conservation_records` contains **2 rows**. The curated CITES
tables that would carry conservation status are **empty**:
`cites_listings` = 0, `v_cites_current_orchids` = 0. Additionally,
`public.orchid_taxonomy.iucn_red_list_category` is **entirely null**.

**Finding:** a genuine source-availability gap (not a wrong-table issue). No
authoritative conservation dataset is populated in production yet.

## Summary
| Domain | Actual | Cause | Actionable? |
| --- | ---: | --- | --- |
| occurrences | 26 | curated table sparse; bulk data has ambiguous linkage | Yes — verify alt-source linkage before repoint |
| conservation | 2 | authoritative tables empty | No — awaits data ingestion |
