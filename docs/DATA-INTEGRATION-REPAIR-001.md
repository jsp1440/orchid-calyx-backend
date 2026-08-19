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

## Occurrence semantics, as encoded

`app/readiness/occurrence_semantics.py` encodes the definition:

> An occurrence is evidence that an orchid taxon occurred at a particular
> place -- a legitimate observation, specimen, collection, or equivalent.

Three rules govern it. **Classification is by declared semantics, never by
shape** -- a record does not become an occurrence because it carries
coordinates, elevation, a GBIF key or a taxon name, because vendor listings
carry all four. **Unknown types are ambiguous, never occurrences**, so a new
ingest type cannot inflate a count merely by appearing. **Raw source data is
never rewritten**; this is a derived classification applied at read time, and
`source`, `source_record_id`, `gbif_occurrence_key` and `record_type` travel
with every measurement.

`public.records` carries **46 distinct record_type values** across 5,006,022
rows. All 46 are classified; the test suite fails if production grows a 47th.

**Occurrence (3,884,091 rows):** occurrence 2,776,500 · observation 927,446 ·
specimen 139,330 · HUMAN_OBSERVATION 29,390 · OBSERVATION 11,251 ·
herbarium_specimen 145 · species_observation 26 · PRESERVED_SPECIMEN 3.
The three spellings of observation are admitted together because they are the
same evidence under an unnormalised vocabulary.

**Non-occurrence (1,121,931 rows):** occurrence_stub 621,526 · media_record
96,832 · media_observation 69,575 · taxon_profile 64,764 · occurrence_photo
103,007 · observation_photo 53,998 · species_profile 33,650 · video 23,692 ·
conservation_assessment 16,955 · vendor_listing 10,066 · species_photo 9,899 ·
taxonomy_record 9,838 · plus cultivar, hybrid_registration, living_collection,
personal_collection, breeder_catalog, culture_sheet, judging_standard,
knowledge_article, dataset_metadata, literature_title, migration and the rest.

Photographs attached to occurrences (`occurrence_photo`, `observation_photo`)
are excluded deliberately: the occurrence they illustrate is already counted,
and admitting the photo double-counts it.

**Ambiguous, withheld (364 rows):** `community_observation` (346) is named as an
observation but carries zero coordinates and zero event dates, so whether these
are field observations or forum posts is not established; `genomic_record` (18)
qualifies only with a voucher locality, which is not present. Both are withheld
rather than guessed, and ambiguous never counts as an occurrence.

**`occurrence_stub` was resolved from ambiguous by measurement.** All 621,526
carry zero coordinates, zero event dates and zero elevations, so they assert no
place. The 188,292 that carry a GBIF key correspond to the 188,285 rows
`public.orchid_occurrence` records as sourced from
`records_source_record_id_backfill_safe`: they are ingest placeholders whose
real content already lives in the canonical occurrence table. Counting them
would double-count rows measured there.

## How the two occurrence corpora relate

They are **different stages of one pipeline**, not rival corpora, and
`public.orchid_occurrence` is measurably derived from `public.records`. Its own
`source_table` column says so:

| source_table | rows |
|---|---|
| `gbif` | 189,747 |
| `records_gbif_backfill` | 189,685 |
| `records_source_record_id_backfill_safe` | 188,285 |
| `orchid_record` | 6,301 |
| `staging_gbif_images_seed` | 4,922 |
| `records_gbif_backfill_round2` | 1,672 |

379,642 of its 580,612 rows were backfilled out of `public.records`, and
379,731 share a GBIF key with it — the two figures agree. A further 364,879
match on `source_record_id`.

So: **`public.records` is the raw harvest spine; `public.orchid_occurrence` is
the curated, taxonomy-linked projection.** Neither is discarded. The spine keeps
every harvested row including the vendor listings; the projection carries the
`taxonomy_id` that resolves 109,195 of 109,195 into `public.orchid_taxonomy`.

There is also **genuine uncovered occurrence coverage**: 3,884,091 rows in the
spine are occurrence evidence against 580,612 in the projection. Promoting that
remainder is an ingest task, not a measurement one, and is left as such.

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

## Status of the items previously left open

1. **Which record_type values constitute an occurrence — RESOLVED.** Encoded in
   `occurrence_semantics.py` against the owner definition, covering all 46
   production values, with regression tests that fail on an unclassified 47th.
2. **`orchid_taxonomy_id` on the pollinator and mycorrhiza tables — DIAGNOSED,
   repair is an ingest task.** Every populated value is broken: 23 of 23 and 2
   of 2 resolve into `public.orchid_taxonomy` and none into `oc_taxonomy.taxa`.
   The measurement now joins the relation the ids belong to, so both
   relationships measure correctly today. Rewriting the stored ids is a
   production data mutation and is deliberately out of scope here.
3. **`observation` / `OBSERVATION` / `HUMAN_OBSERVATION` — RESOLVED in
   measurement.** All three are admitted as the same evidence, so no rows are
   dropped to a casing difference. Normalising the stored vocabulary is an
   ingest change; the audit no longer depends on it.
4. **Two relations answering "taxonomy" — RESOLVED.** The measurement joins
   every existing taxonomy relation and reports which one resolved, so the
   payload is self-describing rather than silently anchored to one.

Nothing here now requires an owner decision. The remaining work is ingest-side:
promoting the uncovered occurrence rows out of the spine, repairing the stored
`orchid_taxonomy_id` values, and normalising the observation vocabulary. Each is
a mutation of production scientific data and is therefore left to a deliberate,
separately-reviewed change.
