# CALYX-GLOBI-RO-LITERATURE-RELATIONSHIPS-001

## Purpose

Normalize publication-eligible biotic relationships discovered in scientific literature using the same interoperability pattern used by Global Biotic Interactions (GloBI): preserve the source/verbatim relationship language, translate recognized predicates to a controlled subset of OBO Relations Ontology (RO) terms, and retain the ontology URI with the graph edge.

## Context

EOL TraitBank includes ecological interactions as structured graph data, and GloBI is an EOL interaction resource. GloBI's published integration guidance states that verbatim association types are explicitly mapped to supported OBO RO biotic-interaction terms through translation tables.

This pattern is valuable to Orchid Continuum because literature extraction will discover relationships well beyond the small set of legacy graph predicates: pollination, floral visitation, feeding, predation, parasitism, pathogens, hosts, vectors, symbioses, nutrient acquisition, epiphytism, egg laying, co-occurrence, mutualism, and mycorrhizal-host relationships.

## Implemented

### Controlled GloBI/RO vocabulary

Added `runtime/knowledge_graph/biotic_relation_ontology.py`.

It includes the current GloBI-supported RO interaction labels/URIs used for indexing, including examples such as:

- `pollinates` -> `RO_0002455`
- `visitsFlowersOf` -> `RO_0002622`
- `preysOn` -> `RO_0002439`
- `parasiteOf` -> `RO_0002444`
- `pathogenOf` -> `RO_0002556`
- `epiphyteOf` -> `RO_0008501`
- `acquiresNutrientsFrom` -> `RO_0002457`
- `ectomycorrhizalHostOf` -> `RO_0002804`
- `arbuscularMycorrhizalHostOf` -> `RO_0002806`

A deliberately conservative verbatim translation table maps common scientific prose (for example, `visits flowers of`, `feeds on`, `parasite of`, `infects`, `grows epiphytically on`) to canonical GloBI labels. Unknown predicates fail closed; there is no fuzzy relationship invention.

### Knowledge Graph vocabulary registration

All supported GloBI/RO interaction labels are registered as `biotic_interactions` edge types. This allows native graph traversal while preserving interoperability with GloBI/EOL through the canonical label and RO URI.

### Reviewed literature relationship materialization

The strict `publication_eligible_paper_graph` projection now emits a direct taxon-to-taxon biotic interaction edge only when all of the following are true:

1. the source scientific claim has a normalized evidence record with an explicit `eligible_for_publication` decision;
2. the claim contains an explicit predicate that maps to a supported GloBI/RO interaction type;
3. the subject and object entities each resolve exactly and unambiguously to active canonical Knowledge Graph taxa;
4. the two endpoints are distinct.

The emitted edge retains:

- canonical GloBI interaction label;
- OBO RO URI;
- verbatim source predicate;
- source claim id;
- subject/object extraction entity ids;
- publication key;
- publication-eligible normalized-record ids;
- extraction evidence class, confidence, and publication-eligible state.

This means a reviewed statement such as `Apis mellifera visits flowers of Laelia anceps` can become a semantically interoperable `visitsFlowersOf` edge between the exact canonical taxa, while the supporting claim/evidence/publication structure remains separately inspectable.

## Epistemic boundary

Co-occurrence in a paper does not create an interaction. Two taxon mentions do not create an interaction. An unrecognized verb does not create an interaction. An unreviewed or non-publication-eligible claim does not create an interaction. A fuzzy or ambiguous taxon resolution does not create an interaction.

The relationship edge is therefore a normalized representation of a governed reviewed claim, not an AI inference from proximity in text.

## Validation coverage

Added `tests/test_globi_ro_literature_relations.py` covering:

- controlled verbatim-to-GloBI normalization;
- canonical RO URI retention;
- unknown predicates fail closed;
- graph domain registration;
- publication-eligible exact taxon-to-taxon relationship creation;
- provenance payload retention;
- missing canonical endpoint blocks the relationship;
- removal of publication eligibility blocks the relationship.

The focused KG validation workflow now includes the relation ontology module, graph vocabulary, and these regressions.

## Production boundary

No production graph relationship was added by this implementation. These interaction edges enter the existing reviewed-literature dry-run/publication path and remain subject to the same explicit production confirmation, single-writer lock, validation, and transactional rollback boundary.
