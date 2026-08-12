# CALYX Knowledge Graph — live production scientific catalog discovery

Date: 2026-08-12
Parent integration: CALYX-KG-MATERIALIZATION-001 / PR #901

## Evidence source

Owner-operated read-only PostgreSQL catalog inspection was run from the deployed Render backend against the production `DATABASE_URL`. No INSERT, UPDATE, DELETE, DDL, migration, or Knowledge Graph publication occurred.

## Key finding

The legacy source registry points at only a small subset of the scientific warehouse. Production contains richer occurrence, elevation, trait, literature, habitat, ecology, pollinator, fungal, and evidence-bearing relations that are not represented by the current persisted `oc_graph` materialization.

The production graph baseline remains 37,641 nodes / 70,602 edges with only 26 occurrence nodes, 2,807 trait nodes, 29 publication nodes, 115 pollinator nodes, 51 image nodes, and 2 conservation-assessment nodes. The live catalog therefore confirms that edge-type presence is not equivalent to scientific corpus integration.

## Live-discovered occurrence and elevation relations

High-priority production relations discovered in `public` include:

- `public.oc_occurrences`
- `public.orchid_occurrence`
- `public.orchid_occurrence_filtered`
- `public.records`
- `public.v_records_elevation`
- `public.record_traits`
- `public.species_elevation_profile`
- `public.taxon_elevation_profile`

`public.oc_occurrences` exposes occurrence identity plus `species_id`, `genus_id`, `decimal_latitude`, `decimal_longitude`, `elevation_m`, `country`, `source`, and raw provenance.

`public.orchid_occurrence` / `_filtered` expose a substantially richer scientific record including `taxonomy_id`, scientific name, country, region, locality, decimal coordinates, minimum/maximum/point elevation, growth habit, habitat description, climate preference, temperature range, humidity preference, source fields, event date, observer/collector, and multiple elevation derivation/provenance fields.

`public.records` and `public.v_records_elevation` expose source record identity, matched taxon identity, scientific name, coordinates, country/state/locality, event date, citation/raw record, and a large set of raw/derived elevation values, methods, models, confidence and provenance fields.

These relations are candidates for the bulk occurrence/elevation publication path. They are not authorized for publication merely because their schema is now known; row counts, taxon resolution coverage, duplicate semantics, source precedence, and provenance quality must be measured first.

## Live-discovered trait relations

Production contains a much richer trait estate than the current `oc_views.trait_resolved_v4` projection alone:

- `public.oc_trait_consensus`
- `public.oc_trait_consensus_normalized`
- `public.oc_trait_knowledge`
- `public.trait_assertions`
- `public.trait_documents`
- `public.trait_elevation`
- `public.trait_geography`
- `public.trait_growth_habit`
- `public.trait_observations`
- `public.traitbank_orchid_traits`
- `public.traits`

The catalog shows evidence-bearing fields including accepted taxon ids, canonical names, normalized traits, trait categories/families, numeric and text values, units, support counts/weights, confidence, source schema/table/primary key, evidence quotes/locators/URLs, method, raw text, review status, geography and elevation context.

This supports a graph model in which a taxon can connect not only to a normalized trait concept but also to the assertion/observation and its evidence/provenance.

## Live-discovered literature and scientific-method relations

`public.research_documents` exposes document metadata including title, authors, year, publisher, DOI/ISBN, file identity, page count, document type, themes, genera covered, language, abstract, keywords and citation metrics.

`public.trait_documents` exposes source-document identity, title, authors, year, license/source URL/file path/hash plus extraction state and extracted text.

These relations complement the existing `PaperKnowledge` extraction model, which already represents sections, entities, measurements, claims, evidence, normalized evidence records, relationships, figures, tables and references. Future graph publication should preserve publication -> section -> observation/method/measurement/result/conclusion/citation structure rather than flattening a paper into a single metadata node.

## Live-discovered habitat, ecology, pollinator and fungal relations

Additional production relations include:

- `public.oc_species_habitat_claims`
- `public.orchid_ecology_relationships`
- `public.orchid_ecology_inference`
- `public.orchid_fungus_associations`
- `public.pollinators`
- `public.pollinator_lifecycles`
- `public.prey_predator_relationships`

`public.oc_species_habitat_claims` exposes taxonomy identity, habitat class/text, elevation minimum/maximum, climate zone, substrate, canopy cover, moisture regime, source/citation text and URL, observed-vs-inferred status, confidence, review state and provenance.

`public.orchid_fungus_associations` exposes orchid and fungal taxon identities/names, association type/specificity/life stage, interaction notes, confidence, source URL/DOI/year, country/locality, latitude/longitude/elevation, soil/habitat/climate and environmental fields.

These schemas demonstrate that habitat, elevation and biotic interaction graph materialization can preserve direct scientific evidence and spatial/environmental context rather than reducing them to labels.

## Architectural consequence

The canonical graph target must support at least:

`taxon -> occurrence -> coordinates/place/elevation`

`taxon -> trait <- assertion/observation -> evidence -> source`

`taxon -> habitat claim -> habitat/elevation/climate -> citation`

`taxon -> fungal/pollinator interaction -> partner taxon -> evidence/source`

`taxon -> publication -> section -> observation/hypothesis/method/measurement/result/conclusion -> citation/evidence`

Raw measurements and derived profiles must remain distinguishable. Numeric elevation should remain queryable as a measurement on occurrence/elevation evidence; standardized ranges/profile nodes can be additional graph concepts rather than replacing the underlying values.

## Implementation disposition

`runtime/knowledge_graph/scientific_corpus_inventory.py` was expanded to inventory these live-discovered relations. Inclusion in that inventory is read-only and explicitly does not authorize publication.

Next required proof is row-count and taxon-resolution coverage for the highest-value candidates, especially `public.orchid_occurrence`, `public.records`, the trait assertion/consensus relations, `public.research_documents`, `public.trait_documents`, `public.oc_species_habitat_claims`, and `public.orchid_fungus_associations`.

Production graph mutation remains owner-governed and has not occurred in this discovery pass.
