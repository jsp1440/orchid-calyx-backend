# BUILD-064 Deliverable 1 — Identifier Crosswalk Report

Read-only investigation. No production writes. Verification date: 2026-07-15.

## Objective
Determine, for every partially connected domain, whether an authoritative
taxonomic **identifier** relationship exists so that name-matching can be
eliminated or reduced.

## Taxonomic landscape (three coexisting backbones)
| Backbone | Table | Rows | Id range | External authority linked |
| --- | --- | ---: | --- | --- |
| KG backbone | `public.taxonomy_species` | 33,791 | 1..33,791 | **POWO only** (`taxonomy_authority_links`, 2,837) |
| Orchid legacy | `public.orchid_taxonomy` | 68,086 | 517..138,553 | **GBIF** (`gbif_taxon_key`, 62,994) + iNat |
| OC curated | `oc_taxonomy.taxa` | 31,840 | 2..34,780 | GBIF via `taxon_external_ids` (48,175) |

The name-join domains (pollinators, mycorrhiza) carry `orchid_taxonomy_id`,
which is an identifier into **`public.orchid_taxonomy`**, NOT the KG backbone.
Literature carries no identifier at all (scientific_name only).

## Authoritative identifier relationships found
- **`oc_taxonomy.taxon_crosswalk`** (10,070 rows, all `exact_match`,
  confidence 1.0) maps `orchid_taxonomy_id` ↔ `oc_taxonomy.taxa.taxon_id`.
  Both sides validate 100% against their parent tables.
- **`oc_taxonomy.taxon_external_ids`** — 48,175 GBIF ids keyed by
  `orchid_taxonomy_id`.
- **`public.taxonomy_authority_links`** — 2,837 **POWO** ids keyed by backbone
  `accepted_taxon_id` (⊆ `taxonomy_species.id`).
- `public.external_refs` — WFO ids (21,056), keyed by opaque `oc_taxon_id`
  hashes (not directly joinable to either integer backbone).

## The critical gap: no pure-id bridge between the two backbones
The two backbones are cross-referenced to **different authorities** — the KG
backbone to POWO, the orchid-legacy space to GBIF. A GBIF-key join from
`orchid_taxonomy` to the backbone's authority links returns **0** matches, so
there is no shared-authority identifier bridge at scale.

The best available id-anchored path is therefore a **hybrid**:
```
domain.orchid_taxonomy_id
  → oc_taxonomy.taxon_crosswalk (id→id, confidence-scored)
  → oc_taxonomy.taxa (id)
  → public.taxonomy_species  (canonical-name equality — final hop)
```
This upgrades the join from a *domain free-text* name match to an
*authoritative-id + curated-crosswalk + canonical-name* match. The final hop is
still a name equality because no id crosswalk exists between the taxa curated
space and the KG backbone (`taxa.source_record_id` ∈ `taxonomy_species.id` = 0).

## Reusable crosswalk produced
`docs/crosswalks/orchid_taxonomy_to_backbone_crosswalk.csv` — 10,409 pairs
(`public.orchid_taxonomy.id → public.taxonomy_species.id`) with method,
confidence, authority, date, provenance, quality_score. See Deliverable 7.

## Per-domain outcome
| Domain | Identifier available? | Recommended strategy |
| --- | --- | --- |
| pollinators | Yes (`orchid_taxonomy_id`, all 4 in crosswalk) | id-anchored hybrid via crosswalk |
| mycorrhiza | Yes (`orchid_taxonomy_id`) | id-anchored hybrid + operator review of collisions |
| literature | **No** (name only) | remains a pure name join until upstream emits an id |
