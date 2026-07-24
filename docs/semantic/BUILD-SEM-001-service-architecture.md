# BUILD-SEM-001 — Semantic Service Architecture

## Service map

The recommended architecture is a modular semantic domain with clear APIs, not a fleet of independently deployed microservices. Split deployment only when load, ownership, or failure isolation requires it.

| Service/module | Responsibility | Foundation |
|---|---|---|
| Concept Registry | concept identity, schemes, lifecycle, releases | ontology registry/term services |
| Lexical Registry | preferred, alternate, historical, multilingual labels and abbreviations | ontology synonyms |
| Definition Service | sourced, audience-specific definitions and explanations | term definition |
| Mapping Service | external ontology and Darwin Core crosswalks | external IDs |
| Annotation Service | mention recognition, selectors, proposals and review | semantic extraction |
| Resolution Service | normalization, ambiguity handling, contextual ranking | deterministic resolver |
| Relationship Service | typed concept relations and validation | term hierarchy + graph vocabulary |
| Asset Service | illustration, image, video, audio, diagram and 3D metadata | new |
| Evidence/Provenance Service | evidence anchors, hashes, attribution, validation | existing evidence registries |
| Semantic Search Service | lexical/vector/concept expansion and filters | semantic index |
| Link Service | literature, species, trait, pollinator, mycorrhiza, habitat and evolution links | graph projections |
| Delivery/Explain Service | concept cards, explanations, navigation and exports | new façade |

## API capabilities

Versioned read contracts should include:

- `GET /api/semantic-knowledge/concepts/{uri-or-id}`;
- `GET /api/semantic-knowledge/concepts:search`;
- `POST /api/semantic-knowledge/concepts:resolve`;
- `GET /api/semantic-knowledge/concepts/{id}/relations`;
- `GET /api/semantic-knowledge/concepts/{id}/assets`;
- `GET /api/semantic-knowledge/concepts/{id}/links`;
- `GET /api/semantic-knowledge/concepts/{id}/explain?audience=...`;
- `POST /api/semantic-knowledge/annotations:propose`;
- `GET /api/semantic-knowledge/releases/{version}`;
- exports for JSON, SKOS/RDF and a documented Darwin Core profile.

Existing `/api/ontology`, `/api/semantic`, and `/api/semantic-index` contracts remain until compatibility and migration plans are approved.

## Resolution pipeline

1. detect language and candidate mentions;
2. expand abbreviations within document/context;
3. normalize typography without erasing scientifically meaningful characters;
4. retrieve exact and synonym matches within allowed schemes;
5. apply contextual features such as neighboring concepts, entity type and taxon;
6. return ranked candidates with reason codes;
7. auto-accept only policy-approved, deterministic cases;
8. route ambiguity to review;
9. record the resolver and concept release versions.

Embedding similarity may suggest candidates but cannot establish equivalence.

## Search architecture

Semantic search combines:

- lexical matching over labels, definitions and identifiers;
- concept expansion over approved hierarchy/relations;
- vector retrieval over documents and concept representations;
- structured filters for taxon, trait, organ, habitat, evidence and release;
- provenance-aware ranking;
- explicit expansion controls for research users.

Results return matched concepts, expansion path, evidence anchors, and ranking explanation. Indexes are rebuildable projections.

## Link services

Links should be typed projections rather than arrays embedded in a concept record:

- literature links include cited concept, passage, document and claim role;
- species links distinguish defining, observed and educational associations;
- trait links use the structured trait assertion pattern;
- pollinator and mycorrhizal links name both participants and interaction role;
- habitat links use ENVO mappings where available;
- evolutionary context separates hypotheses, clades, characters and evidence.

## Calyx integration contract

Before answering, Calyx calls resolution/search and receives a bounded grounding envelope. The envelope contains concept IDs, labels, definitions, relationships, evidence links, navigation routes, release versions, permissions and ambiguity. After answering, Calyx returns cited concept IDs and evidence references. Proposed new concepts or mappings go to candidate review, never directly to the registry.

Cross-workbench navigation is registry-driven: a concept response advertises applicable routes such as species dossier, paper passage, Knowledge Graph neighborhood, Conservatory help, Atlas filter, Matrix comparison or lesson.

## Events and projections

Canonical changes emit outbox events such as `ConceptCreated`, `LabelChanged`, `MappingApproved`, `ConceptDeprecated`, `ReleasePublished`, and `AssetLinked`. Consumers rebuild graph, lexical, vector, UI cache, and AI-grounding projections idempotently. Events carry aggregate ID, version, actor, provenance and correlation ID.

## Security and governance

- public read access is limited to released concepts and licensed assets;
- editor, reviewer, ontology steward and release manager are distinct roles;
- all writes are authenticated and audited;
- bulk imports are staged and diffed before approval;
- source licenses and restricted content flow into delivery policy;
- model-generated explanations are labeled and cannot overwrite curator content.

## Reliability and observability

Track resolution precision/recall, unresolved rate, ambiguity rate, stale mappings, orphan concepts, missing language coverage, asset accessibility coverage, search zero-result rate, grounding citation coverage, and projection lag. Every response declares data/release version. Canonical writes use optimistic concurrency and an outbox; projections tolerate replay.

## Accessibility and multimodality

Delivery selects compatible renditions and always supplies text alternatives. Voice uses pronunciation, language and transcript resources. Animated and 3D assets expose reduced-motion/static alternatives and keyboard-readable structure. Interactive hotspots reference stable concept IDs.
