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

### Retrospective corpus backfill

Added `runtime/knowledge_graph/globi_corpus_backfill.py` and `scripts/audit_globi_literature_backfill.py` so the GloBI/RO normalization is not limited to newly harvested papers.

The backfill walks the canonical literature-extraction bundles already present in Orchid Continuum and, for each bound `LITERATURE_DOCUMENT`:

1. reloads the persisted extraction;
2. reloads the immutable source bytes;
3. revalidates the canonical source binding and evidence-integrity proof;
4. resolves taxon entities using the exact active Knowledge Graph resolver;
5. runs the strict publication-eligible paper graph projection;
6. extracts only recognized GloBI/RO taxon-to-taxon interaction edges;
7. carries the source paper, DOI where present, claim statement, evidence excerpts, section/page/character spans, publication-eligible normalized-record ids, source hash and binding fingerprint into a contribution candidate record.

The scanner is read-only and paginated. It does not publish to `oc_graph`, alter review state, or contact GloBI.

### GloBI contribution candidate queue

Every recovered reviewed interaction is emitted with `candidate_status=candidate_for_globi_review`. Novelty is deliberately not guessed.

If no separately versioned GloBI snapshot is supplied, the record is marked `not_checked_against_globi`. If a known GloBI interaction identity set is supplied, the same scanner can distinguish `already_present_in_supplied_globi_snapshot` from `candidate_new_to_supplied_globi_snapshot` using the tuple `(sourceTaxonName, interactionTypeName, targetTaxonName)`.

This distinction is mandatory: a new literature record may be new to Orchid Continuum but already known to GloBI. Conversely, a relationship type can be standard RO/GloBI vocabulary while the specific organism pair is a novel interaction record.

`globi_tsv_rows()` produces a GloBI-template-friendly staging representation with `sourceTaxonName`, `interactionTypeName`, `interactionTypeId`, `targetTaxonName`, DOI/citation, source identity and claim notes. It is an export staging format only, not an automatic submission.

A future external contribution workflow should publish only governance-approved candidate records, preserve attribution to the original paper authors, and version the exported dataset independently (for example through a public repository and/or DOI-bearing archive) before asking GloBI to index it.

## Epistemic boundary

Co-occurrence in a paper does not create an interaction. Two taxon mentions do not create an interaction. An unrecognized verb does not create an interaction. An unreviewed or non-publication-eligible claim does not create an interaction. A fuzzy or ambiguous taxon resolution does not create an interaction.

The relationship edge is therefore a normalized representation of a governed reviewed claim, not an AI inference from proximity in text.

The corpus backfill also does not claim an interaction is new to GloBI unless it has been compared against a named/versioned GloBI snapshot. External contribution remains a separate governance action.

## Validation coverage

`tests/test_globi_ro_literature_relations.py` covers:

- controlled verbatim-to-GloBI normalization;
- canonical RO URI retention;
- unknown predicates fail closed;
- graph domain registration;
- publication-eligible exact taxon-to-taxon relationship creation;
- provenance payload retention;
- missing canonical endpoint blocks the relationship;
- removal of publication eligibility blocks the relationship.

`tests/test_globi_corpus_backfill.py` additionally covers:

- retrospective screening of an already-existing reviewed paper;
- source/target taxon and RO identity preservation;
- no graph mutation or external submission during backfill;
- no novelty claim without a supplied GloBI snapshot;
- known-snapshot novelty classification;
- GloBI-template export rows preserving reference and relationship identity.

The focused KG validation workflow now includes the relation ontology, retrospective corpus scanner, export operator and both regression suites.

## Production and external-publication boundary

No production graph relationship and no external GloBI record was added by this implementation. Reviewed interaction edges enter the existing reviewed-literature dry-run/publication path and remain subject to explicit graph-publication confirmation, single-writer locking, validation and rollback.

Submitting or publishing an Orchid Continuum interaction dataset for GloBI indexing is a separate external-publication governance boundary. The contribution candidate queue is deliberately designed to accumulate and audit evidence before that decision is made.
