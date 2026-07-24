# BUILD-SEM-001 — Semantic Knowledge Roadmap

## Sequencing principle

Stabilize identity and governance before adding rich interfaces or AI automation. Each phase is additive, separately authorized, and preserves existing runtime contracts until migration evidence supports change.

## Phase 0 — Decisions and baselines

Deliver:

- approve scope, ownership, URI namespace and terminology;
- inventory production data and active ontology registries;
- define competency questions and user journeys;
- establish quality baselines for resolution and search;
- select ontology licenses and release policies.

Exit: architecture decision records and named stewards are approved.

## Phase 1 — Concept foundation (highest-priority next build)

Proposed build: **BUILD-SEM-002 — Canonical Concept Registry Foundation**.

Deliver:

- additive concept, scheme, label, definition, relation and mapping contracts;
- stable URI generation;
- SKOS-aligned JSON representation;
- compatibility mapping from existing ontology terms/synonyms;
- read-only concept detail, search and resolve APIs;
- release/version manifest;
- conformance tests and no-runtime-regression proof.

Exit: one existing glossary/ontology registry can be represented without data loss and existing endpoints continue to operate.

## Phase 2 — External standards and Darwin Core

Deliver:

- versioned Darwin Core crosswalk profile;
- curated PO, TO, PATO, ENVO and RO mapping workflow;
- import staging, release pinning, license recording and mapping review;
- RDF/SKOS export and round-trip tests;
- clear taxon/name/concept separation.

Exit: approved mappings answer defined competency questions and exports validate.

## Phase 3 — Literature annotation

Deliver:

- Web Annotation-compatible targets/selectors;
- abbreviation, language, negation and uncertainty capture;
- concept-aware recognition and ambiguity review;
- bulk annotation API;
- evidence-linked clickable paper prototype.

Exit: a paper passage can be resolved, reviewed, cited and reopened against its source revision.

## Phase 4 — Semantic retrieval and graph projection

Deliver:

- concept lexical/vector representations;
- controlled query expansion and filters;
- graph projection from concept relations;
- typed links to species, traits, habitats, pollinators and mycorrhizae;
- measurable search relevance evaluation.

Exit: search and graph return the same identifiers and explain expansion/provenance.

## Phase 5 — Workbench delivery

Deliver:

- concept cards and hover definitions;
- Species Dossier and Conservatory integrations;
- Atlas/Matrix/Research filters and cross-navigation;
- audience-specific explanations;
- accessible media manifests and interactive diagrams.

Exit: at least three workbenches consume the shared API without local terminology forks.

## Phase 6 — Calyx grounding

Deliver:

- question concept resolution;
- versioned grounding envelope;
- safe concept expansion;
- explanation adaptation;
- cited reasoning and cross-workbench links;
- candidate proposal path and evaluation suite.

Exit: Calyx answers a benchmark set with traceable concept/evidence citations and no canonical writes.

## Phase 7 — Advanced learning and media

Deliver:

- prerequisite graphs, quizzes and adaptive learning paths;
- 3D/animated botanical structures;
- voice and pronunciation;
- multilingual editorial workflows;
- comprehensive accessibility audits.

Exit: advanced experiences meet licensing, accessibility, performance and semantic conformance gates.

## Cross-phase controls

Every phase includes:

- additive migration and rollback/recovery plan;
- data lineage and license review;
- API and semantic versioning;
- curator workflow testing;
- performance and accessibility checks;
- metrics and release notes;
- documentation-only design review before runtime implementation.

## Dependencies

Concept identity precedes annotation, graph and AI integration. External mappings precede broad concept expansion. Asset governance precedes 3D/voice delivery. Calyx grounding follows stable read APIs and evaluation data.

## Success measures

- percentage of displayed terms backed by stable concept IDs;
- resolution accuracy and reviewer agreement;
- percentage of definitions/mappings with evidence;
- stale external mapping rate;
- concept reuse across workbenches;
- search success and expansion transparency;
- Calyx grounding citation coverage;
- multilingual and accessibility coverage;
- zero unreviewed canonical promotions.
