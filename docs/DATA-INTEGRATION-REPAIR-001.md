# DATA-INTEGRATION-REPAIR-001

Read-only repair of the taxonomy joins behind the executive Overall Audit.
Every number here was measured against production and is committed under
`docs/evidence/audit-measurement-002/`.

Nothing is deployed. No scientific data is mutated. No graph edges are published.

## The single cause

This schema does not anchor every corpus to the same taxonomy relation, and the
measurement assumed it did. `oc_taxonomy.taxa` holds 31,840 rows;
`public.orchid_taxonomy` holds 69,485. Measured resolution:

| Corpus | key | → `public.orchid_taxonomy` | → `oc_taxonomy.taxa` |
|---|---|---|---|
| `oc_interactions.orchid_interaction_edges` | `orchid_taxonomy_id` | 23 of 23 | 0 |
| `oc_mycorrhiza.orchid_fungal_associations` | `orchid_taxonomy_id` | 2 of 2 | 0 |
| `public.oc_species_habitat_claims` | `taxonomy_id` | 695 of 695 | 2 |
| `public.orchid_occurrence` | `taxonomy_id` | 109,195 of 109,195 | 41,278 |
| `oc_atlas.occurrences` | `taxon_id` | — | 26 of 26 |

The habitat "gap" of 695 claims reaching 2 taxa was never a data gap. It was the
audit joining the wrong table and reporting the shortfall as a finding about the
archive.

Every existing taxonomy relation is now joined against and the best-resolving
attempt wins. Reach outranks join strength, with id-over-name only as a
tie-break: ranking by strength first would have picked mycorrhiza's 2-row id join
over its 462-row name join and called 0.4% coverage an improvement. When a name
join wins, the result says so and states what the id join reached, so name
matching stays a visible documented fallback rather than a silent default.

## Before and after, measured against production

Deployed release `34352e39` reports 2 measured-present and 8 unmeasured.

| Relationship | Deployed | After first repair | After join repair |
|---|---|---|---|
| `taxonomy_to_occurrences` | unmeasured | 26 rows / 20 taxa | **109,195 / 3,596** |
| `taxonomy_to_habitat` | unmeasured | 2 / 2 | **695 / 655** |
| `taxonomy_to_climate` | unmeasured | 18,621 | **26,788** |
| `taxonomy_to_mycorrhiza` | unmeasured | 347 / 146 | **462 / 218** |
| `taxonomy_to_literature` | unmeasured | 29 / 15 | **35 / 20** |
| `taxonomy_to_pollinators` | unmeasured | 23 (name join) | 23 (**id join**) |
| `taxonomy_to_conservation` | unmeasured | 2 / 2 | 2 / 2 |
| `taxonomy_to_elevation` | unmeasured | **measured-absent** | present, 7 |
| `taxonomy_to_images` | measured-present | — | 971,105 / 30,807 |
| `knowledge_graph_node_edge_integrity` | measured-present | — | integrity passed |

Totals: **2 present / 8 unmeasured → 8 present / 0 absent / 0 unavailable**, plus
the two the deployed release already measured.

## A defect this work found in its own output

The first production run returned three relationships `absent`. Two were wrong,
in exactly the way this line of work exists to prevent.
`oc_mycorrhiza.orchid_fungal_associations` holds 462 rows; two carry
`orchid_taxonomy_id` and neither resolves. Preferring the id join and stopping
there reported 462 documented fungal associations as absent, without ever trying
the `orchid_scientific_name` join the source registry itself uses.
`oc_interactions.orchid_interaction_edges` failed the same way on 23 rows.

Absence is now reported only when every join the schema supports has run and all
of them found nothing. Both cases are pinned by regression tests.

## The occurrence source, and why it is not the biggest relation

`oc_atlas.occurrences` (26 rows) is not canonical, and
`oc_views.occurrences_enriched` is a view over it. `public.orchid_occurrence`
(580,612) is promoted: an explicit `taxonomy_id` resolving without a single miss,
plus the provenance an occurrence corpus needs — `source_table`,
`source_record_id`, `canonical_gbif_occurrence_key`, `taxon_match_method`.

`public.records` is larger still at 5,006,022 rows, carries `gbif_occurrence_key`,
coordinates, event dates and 2,934,913 elevation values, and reaches taxonomy by
name on 847,517 rows. It is **not** promoted. Its `record_type` breakdown:

| record_type | rows | | record_type | rows |
|---|---|---|---|---|
| occurrence | 2,776,500 | | media_record | 96,832 |
| observation | 927,446 | | media_observation | 69,575 |
| occurrence_stub | 621,526 | | taxon_profile | 64,764 |
| specimen | 139,330 | | species_profile | 33,650 |
| occurrence_photo | 103,007 | | video | 23,692 |
| | | | vendor_listing | 10,066 |

It is a universal ingest spine. Counting it whole would report videos and vendor
listings as orchid occurrences. A real and much larger occurrence corpus does
live inside it, but deciding which `record_type` values constitute an occurrence
is curatorial: `occurrence_stub` alone is 621,526 rows of unclear standing, and
`observation`, `OBSERVATION` and `HUMAN_OBSERVATION` exist as three separate
values — a data-quality finding in its own right.

It is therefore *listed* so the masking check states the discrepancy on every
audit, and a regression test pins the ordering so it cannot be promoted on size
alone.

## Elevation

`oc_env.taxon_elevation_profiles`, which the elevation adapter declares, does not
exist in production — confirmed by catalog probe, which is a stronger statement
than "unverified" and points at different work. The same is true of
`oc_habitat.taxon_habitats`. Both stay disabled fail-closed in the Knowledge
Graph source registry, with the measured reason recorded and the candidate
replacement named but not adopted.

The elevation values themselves — 2,934,913 of them — sit in `public.records`,
whose id key is entirely unpopulated. So `taxonomy_to_elevation` genuinely cannot
exceed 7 through any relation with working id linkage today. This is gated on the
same curatorial decision as the occurrence source.

## Open items for the owner

1. Decide which `record_type` values in `public.records` constitute an
   occurrence. This unblocks both the occurrence metric and elevation.
2. Repair `orchid_taxonomy_id` on the pollinator and mycorrhiza tables. Every
   populated value is broken; the name join is carrying both relationships.
3. Reconcile `observation` / `OBSERVATION` / `HUMAN_OBSERVATION` into one vocabulary.
4. Two relations answer "taxonomy" in the same audit payload:
   `taxonomy_to_images` measures against `public.orchid_taxonomy` while the
   taxonomy metric counts `oc_taxonomy.taxa`.
