# BUILD-SEM-001 — Canonical Concept Model

## Core aggregate

`Concept` is the stable semantic identity. A label, definition, image, taxon record, annotation, or embedding is not the concept itself.

| Entity | Required responsibilities |
|---|---|
| Concept | URI, local key, type, scheme, status, steward, created/revised timestamps, replacement/supersession |
| ConceptScheme | authority, scope, version, release, license, language policy |
| Label | text, language, script, status, label type, temporal validity, provenance |
| Definition | text, language, audience, definition type, source/evidence, status |
| ConceptRelation | subject, predicate, object, status, evidence, provenance, validity |
| ExternalMapping | external URI, mapping predicate, target release, confidence, review status, evidence |
| SemanticAsset | media identity, role, rendition, selector/region, license, accessibility, provenance |
| Annotation | source target/selectors, concept body, motivation, creator, confidence, review state |
| ConceptLink | link from a concept to taxon, species, trait, literature, habitat, pollinator, mycorrhiza or workbench route |
| ConceptRelease | immutable manifest of included versions and changes |

## Identifier policy

Proposed URI pattern:

`https://id.orchidcontinuum.org/concept/{uuid}`

URIs are opaque, permanent, and never encode labels or hierarchy. Database IDs remain implementation details. External ontology URIs are retained; a local URI is not required solely to proxy an external concept unless local editorial content, mappings, or lifecycle need a stable aggregate.

## Concept types

Initial controlled types:

- botanical structure;
- morphology;
- trait/quality;
- process;
- developmental stage;
- habitat/environment;
- taxonomic concept;
- nomenclatural name;
- organism interaction;
- cultivation/care;
- conservation;
- research method;
- general botanical glossary;
- educational/editorial concept.

Types organize validation profiles; they do not imply disjoint OWL classes.

## Labels

Label types include preferred, alternate, hidden/search, historical, abbreviation, scientific name, common name, misspelling, and transliteration. Exactly one preferred label per concept, language, and editorial context is allowed. Historical labels retain validity dates and evidence. Search-only misspellings must never display as preferred text.

## Definitions and explanations

Definitions are multiple, versioned resources:

- normative scientific definition;
- concise glossary definition;
- grower explanation;
- learner explanation by level;
- accessibility/plain-language explanation;
- historical definition.

Audience variants derive from, and link to, a normative meaning; they do not silently redefine it.

## Relationships

Minimum predicates:

- broader, narrower, related;
- part of / has part;
- develops from / develops into;
- bears quality / quality of;
- occurs in habitat;
- interacts with;
- pollinated by;
- mycorrhizal partner of;
- associated with taxon;
- prerequisite for;
- illustrated by;
- supported by / contradicted by;
- exact, close, broad, narrow and related mapping;
- replaced by / supersedes.

Each relationship records its authority. Vocabulary relations and scientific assertions must be distinguishable.

## Semantic assets

Assets cover illustrations, photographs, videos, audio, animations, interactive diagrams and 3D models. Required metadata includes role, creator, rights/license, source, language, caption, alt text or transcript, accessibility characteristics, technical rendition, and review status. Selectors can identify a region, time segment, mesh/node, or diagram hotspot linked to a concept.

## Annotation model

Adopt a Web Annotation-compatible shape:

- target: document/revision URI plus text-position and text-quote selectors;
- body: concept URI or proposed concept;
- motivation: classifying, identifying, describing, linking;
- evidence: exact excerpt and source hash;
- metadata: extractor/model/version, confidence, language, negation, uncertainty;
- lifecycle: proposed, reviewed, accepted, rejected, superseded.

## Trait pattern

A trait assertion contains:

- subject taxon/organism/specimen;
- entity or bearer concept;
- quality/trait concept;
- categorical state or numeric value and unit;
- method and measurement context;
- developmental stage and environmental context;
- evidence and provenance;
- confidence and review status.

This pattern maps to Darwin Core MeasurementOrFact for exchange but retains richer internal semantics.

## Compatibility with existing tables

Existing `ontology_registries` maps toward ConceptScheme; `ontology_terms` toward Concept; `ontology_synonyms` toward Label; hierarchy toward a restricted ConceptRelation; `external_ids` toward ExternalMapping; evidence and audit tables remain reusable. Migration should add new normalized resources alongside existing fields, backfill, provide compatibility views, and only later deprecate redundant columns. No destructive migration is proposed.

## Invariants

- identifiers are never reused;
- canonical changes are attributable and reviewable;
- accepted concepts belong to a released or active scheme;
- mappings name source and target releases;
- definitions and displayed media satisfy licensing requirements;
- no automatic extraction directly mutates canonical concepts;
- every AI grounding package declares semantic release/version;
- deprecation identifies replacements when appropriate.
