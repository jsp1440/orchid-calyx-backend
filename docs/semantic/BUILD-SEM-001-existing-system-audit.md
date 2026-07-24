# BUILD-SEM-001 — Existing Semantic System Audit

Status: architectural audit; documentation only  
Audit baseline: `origin/main` at `7fa2a24` (2026-07-23)  
Scope: tracked repository content available in the backend repository

## Executive finding

The repository does not contain a single Illustrated Glossary product. It contains several production-shaped semantic capabilities built by different workstreams:

1. review-only document extraction in `app/semantic`;
2. controlled terminology and entity resolution in `app/ontology`;
3. lexical/vector indexing in `app/semantic_index`;
4. candidate fact extraction in `app/candidate_knowledge`;
5. canonical taxonomy and controlled graph publication in `runtime/knowledge_graph`;
6. evidence, provenance, publication, and scientific-interpretation services around those cores.

These components are reusable, but they do not yet form a coherent Semantic Knowledge System. In particular, a concept is not yet a first-class, globally addressable, multilingual, media-bearing, versioned object shared by all workbenches.

## Component inventory

| Area | Existing implementation | Maturity | Reuse decision |
|---|---|---:|---|
| Semantic extraction | `app/semantic/*`, migration `076b_semantic_extraction.sql`, six authenticated `/api/semantic` routes | Implemented and tested | Reuse as the annotation/candidate intake boundary |
| Ontology registry | `app/ontology/*`, migration `077_ontology_evidence_registry.sql`, 20 authenticated `/api/ontology` routes | Implemented and tested | Evolve into the Concept Registry; preserve lifecycle and audit behavior |
| Term model | registry, term, preferred label, definition, parent, external IDs, metadata, status, replacement | Useful foundation | Extend; do not replace |
| Synonyms | exact, alternate, historical, abbreviation, misspelling, scientific name, common name | Useful foundation | Extend with language, script, scope, dates, evidence, and label status |
| Resolution | exact, normalized, synonym, fuzzy, manual, unresolved; review and one accepted result | Implemented | Reuse for normalization; add ambiguity/context and bulk annotation |
| Evidence registry | immutable evidence identity, hash validation, provenance and readiness gates | Strong foundation | Reuse for definitions, mappings, annotations, and assertions |
| Semantic index | `app/semantic_index/*`, migration `085_semantic_index.sql`; collections, model registry, runs, vectors, lexical index, anchors, review, tombstones | Implemented foundation | Reuse as retrieval infrastructure, not as concept authority |
| Candidate knowledge | trait, morphology, ecology, geography, phenology, conservation, cultivation candidates | Implemented foundation | Reuse as proposed assertions linked to concepts |
| Knowledge Graph | controlled nodes/edges, vocabulary validation, domain adapters, provenance, taxonomy mapping | Substantial | Treat concepts as governed graph nodes; keep publication gating |
| Canonical taxonomy | accepted-name/synonym resolution and backbone mapping | Substantial | Reuse for taxon concepts; separate nomenclatural/taxonomic identity from glossary concepts |
| Documentation architecture | BUILD-060 through BUILD-088A and BUILD-080 derived architecture corpus | Extensive | Use as provenance, but do not treat generated term lists as an ontology |

## Detailed findings

### `app/semantic`

The extraction system records extraction sessions, immutable evidence spans, candidate entities, candidate relationships, review decisions, and audit events. It explicitly prohibits automatic canonical promotion. This is the correct safety boundary for literature annotation.

Gaps:

- entity types and predicates are strings rather than concept identifiers;
- annotations do not carry motivation, body/target selectors, creator, language, or lifecycle compatible with a web annotation model;
- offsets alone are fragile when source renderings change;
- there is no concept-recognition endpoint or batch annotation exchange format;
- abbreviations, negation, uncertainty, and co-reference are not modeled explicitly.

### `app/ontology`

The ontology registry already supports versioned registries, controlled term status, hierarchy, preferred labels, definitions, external identifiers, synonyms, deterministic resolution, evidence validation, audit events, and publication readiness. `OntologyType.GLOSSARY` proves the glossary was anticipated as a registry type.

Gaps:

- `preferred_label` and `definition` are single text fields with no language, audience, source, or history;
- only one parent relationship is available and its semantics are unstated;
- no typed concept-to-concept relationships;
- no mapping predicates (`exactMatch`, `closeMatch`, `broadMatch`, `narrowMatch`, `relatedMatch`);
- media, educational explanations, and interaction assets are relegated to unstructured metadata;
- registry activation and term activation semantics are incomplete;
- no import/export profiles for SKOS, OWL/RDF, Darwin Core, or ontology releases;
- fuzzy matching is string-based and context-free.

### `app/semantic_index`

The index has reproducible model/configuration records, revision-aware index documents, lexical search records, vectors, source anchors, quality warnings, reviews, versioning, and tombstones. This is an appropriate substrate for semantic retrieval.

Gaps:

- indexed representations are document-centric rather than concept-centric;
- no explicit concept embeddings, label expansion, ontology filters, or concept-aware ranking;
- no public search/query contract was found;
- embeddings must not become canonical identity or silently resolve concepts.

### Knowledge Graph and traits

`runtime/knowledge_graph` provides a controlled vocabulary, validation, canonical taxonomy integration, adapters for traits and other scientific domains, and provenance-aware publication. Candidate extraction recognizes `TRAIT` and `MORPHOLOGY_TERM`.

Gaps:

- graph vocabulary and ontology terms have no declared shared identifier policy;
- trait values lack an explicit, uniform Entity–Quality–Value pattern;
- units, methods, life stage, organ, sex, environmental context, and statistical summaries are not consistently modeled;
- external ontology mappings are not governed in one place.

## APIs, tests, migrations, and documentation

| Capability | APIs | Tests | Persistence/docs |
|---|---:|---|---|
| Semantic extraction/review | 6 routes | `test_build_076b_semantic_extraction.py` | migration 076b |
| Ontology/evidence/readiness | 20 routes | `test_build_077_ontology_registry.py` | migration 077 |
| Semantic index lifecycle | 11 routes | `test_build_085a_semantic_index.py` | migration 085 |
| Knowledge Graph | mounted API plus runtime services | traversal, telemetry, orchestrator, API and taxonomy suites | BUILD-060–068, 088A |

The tests demonstrate component behavior, not end-to-end concept flow. No test proves that a term recognized in literature resolves to a concept, appears in a species dossier, participates in the graph, and grounds a Calyx answer with the same stable identifier.

## Darwin Core audit

Existing taxonomy, occurrence, media, attribution, and identification data can naturally map to Darwin Core terms. The ontology registry's `external_ids` can hold Darwin Core identifiers, but no explicit Darwin Core concept crosswalk or versioned mapping service was found. Darwin Core should describe biodiversity records and events; it should not be stretched into a general botanical anatomy, pedagogy, media, or reasoning ontology.

## Reusable assets

Highest-value reusable components are:

1. registry/version/status/audit mechanics;
2. immutable evidence anchors and review-only extraction;
3. accepted-resolution and publication-readiness gates;
4. lexical/vector index provenance and tombstones;
5. canonical taxonomy resolution;
6. controlled Knowledge Graph publication;
7. candidate trait/morphology extraction.

## Major architectural gaps

- no globally stable concept URI policy;
- no canonical Concept API shared across workbenches;
- no multilingual and audience-specific lexical model;
- no typed relationship and mapping model;
- no semantic asset model for illustrations, diagrams, 3D, audio, or video;
- no formal external ontology import/mapping governance;
- no Darwin Core crosswalk registry;
- no annotation interoperability profile;
- no concept-aware retrieval and Calyx grounding contract;
- no stewardship roles, release process, or compatibility guarantees;
- no end-to-end semantic conformance suite.

## Conclusion

The system should be consolidated by extension and adapters, not rewritten. The next build should establish stable identifiers, a richer concept/label/definition/relationship model, and read-only concept resolution/search contracts while leaving current runtime behavior unchanged until migrations and consumers are separately approved.
