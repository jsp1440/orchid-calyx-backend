# Brain Capture Requirements for Engineering Work

Status: Approved platform requirement

## Principle

No architectural idea, engineering build, scientific workflow, dataset integration, or publication decision is complete until it is represented as searchable, discoverable and repeatable Brain knowledge.

## Required knowledge-object types

- Architecture Object
- Architecture Decision Record
- Engineering Program
- Workstream
- Build
- Requirement
- Data Source
- Dataset Version
- API Contract
- Ontology Concept
- Dependency
- Risk
- Validation Result
- Reproducibility Manifest
- Publication Decision
- Supersession Record

## Minimum metadata

Every object must include:

- durable identifier
- canonical title
- object type
- subsystem
- status
- owner or responsible agent
- created and updated timestamps
- source/provenance references
- semantic keywords and aliases
- related objects
- dependencies
- implementation repository and path when applicable
- validation state
- publication state
- supersedes / superseded-by links

## Lifecycle

`proposed -> reviewed -> approved -> implementing -> implemented -> validated -> published`

Alternative terminal or historical states:

`blocked`, `rejected`, `deprecated`, `superseded`, `archived`

State transitions must be auditable. Historical records may not be silently overwritten or deleted.

## Search and discovery requirements

The Brain must support discovery by:

- exact identifier
- title and alias
- subsystem
- engineer or agent
- build number
- dependency
- status
- data source
- scientific topic
- architecture relationship
- semantic similarity

Example questions that must be answerable:

- What parts of the Atlas depend on geology?
- Show every approved design involving FigureLabs.
- Which Atlas ideas are approved but not implemented?
- Why was Earth Systems made a core Atlas capability?
- Which builds generate thematic maps?
- What evidence and validation support a published map?

## Repeatability requirements

Every generated analysis or artifact must link to a reproducibility manifest containing:

- input dataset identifiers and versions
- source licenses and attribution
- processing code version or commit
- parameters and filters
- spatial and temporal extent
- coordinate reference system
- taxonomy version
- random seed where relevant
- generated outputs and checksums
- validation results
- reviewer and publication decision

## Autonomous Brain Architect / Knowledge Librarian lane

Responsibilities:

- detect new architecture, requirements, decisions and dependencies
- create or update structured Brain objects
- preserve provenance and historical versions
- identify duplicates, contradictions and superseded designs
- maintain ontology and dependency links
- generate living design manuals
- report undocumented or unreproducible engineering work

Boundaries:

- may propose records automatically
- may not silently approve scientific claims
- may not delete superseded decisions
- may not mark a build complete without validation evidence
- may not publish restricted or private material

## Definition of done extension

For every engineering PR, completion requires:

1. architecture documentation updated
2. decision records updated where decisions changed
3. Brain registration payload or adapter updated
4. dependencies and ontology links updated
5. reproducibility information included
6. validation evidence attached
7. implementation status updated

A code-only PR that omits these requirements is incomplete.
