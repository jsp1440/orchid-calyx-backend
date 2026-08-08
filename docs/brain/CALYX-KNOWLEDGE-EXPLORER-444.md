# CALYX Knowledge Explorer — velamen candidate concept slice — issue #444

Date: 2026-08-07
Parent: #433
Program: #421
Status: bounded candidate-only implementation delivered pending exact-head validation; no scientific publication, taxonomy activation, deployment, merge, or production graph mutation performed.

## Goal

Provide a governed educational concept surface that resolves reviewed terms and synonyms into compact and expanded evidence-linked explanations without creating a second scientific authority.

Lifecycle:

`candidate concept → multilevel definitions → evidence spans → licensed/attributed image metadata → figures → evidence-bound relationships → synonym resolution → compact popover / expanded explorer → scientific review`

## Governed engineer profile

`config/knowledge_explorer_engineer_profile.json` defines the Knowledge Explorer Engineer role. The profile permits candidate concept registration, synonym resolution, evidence preservation, and educational rendering while explicitly forbidding autonomous scientific publication, production Knowledge Graph mutation, taxonomy activation, and production deployment.

The profile's output authority is permanently `candidate_only`, and scientific review is mandatory.

## Concept and synonym contracts

Each concept candidate requires:

- stable concept ID;
- preferred term;
- zero or more exact synonyms;
- plain, learner, and advanced definitions;
- at least one evidence span;
- optional images, figures, and relationships;
- deterministic candidate SHA-256.

Resolution is exact and case-insensitive across preferred term and synonyms. Multiple matches remain `ambiguous`; absent matches remain `unmatched`. No fuzzy scientific inference is performed.

## Evidence spans

Every evidence span preserves:

- evidence ID;
- source URI;
- source title;
- exact evidence text;
- source locator;
- SHA-256 of the exact evidence text.

Figures and relationships must reference evidence IDs present in the same candidate concept. Unknown evidence references fail closed.

## Multilevel definitions

Three educational levels are required:

- `plain` — compact accessible explanation;
- `learner` — instructional explanation with more context;
- `advanced` — technical explanation for advanced learners.

The compact popover accepts an explicit level and returns the matching definition rather than silently changing the scientific content.

## Images and figures

Image metadata require:

- stable image ID;
- source URI;
- license;
- attribution;
- non-empty alternative text.

The build preserves metadata only and does not autonomously promote or fetch media.

Figures require a title, description, and one or more known evidence IDs. A figure may reference a known image ID.

## Relationships

The bounded candidate relationship vocabulary is:

- `part_of`;
- `supports_function`;
- `associated_with`;
- `contrasts_with`.

Every relationship preserves source concept, predicate, target concept, and evidence IDs. Unsupported predicates and unknown evidence fail closed.

## Deterministic velamen fixture

Focused tests register three candidate educational concepts:

- velamen;
- aerial root;
- epiphytism.

The velamen candidate includes:

- synonyms `velamen radicum` and `velamen tissue`;
- plain, learner, and advanced definitions;
- two exact fixture evidence spans;
- licensed/attributed image metadata with alternative text;
- an evidence-linked educational figure;
- evidence-linked relationships to aerial root and epiphytism.

The fixture is explicitly candidate/review material. Its deterministic fixture evidence does not constitute scientific publication.

## Compact popover

`GET /brain/mission-control/knowledge-explorer/popover/{term}`

returns:

- term resolution state;
- preferred term;
- selected definition and level;
- synonyms;
- evidence count;
- relationship count;
- permanent non-publication/non-graph-authority state.

## Expanded explorer

`GET /brain/mission-control/knowledge-explorer/concepts/{concept_id}`

returns the full candidate concept plus relationship records enriched with the preferred names of connected concepts when those target candidates are available.

## Protected Mission Control API

Owner/API-key protected routes under:

`/brain/mission-control/knowledge-explorer`

include:

- `POST /candidates` — register an immutable candidate concept;
- `GET /resolve/{term}` — resolve preferred term or synonym;
- `GET /popover/{term}` — compact multilevel educational response;
- `GET /concepts/{concept_id}` — expanded explorer response;
- `GET /readiness` — candidate/review readiness and counts.

## Validation

Dedicated workflow:

`.github/workflows/calyx-knowledge-explorer-444.yml`

Validation covers:

- Python compilation;
- deterministic velamen + two-connected-concept fixture tests;
- synonym and multilevel popover resolution;
- evidence SHA preservation;
- image license/attribution/alt-text requirements;
- figure and relationship evidence references;
- compact and expanded API payloads;
- artifact-registry regressions;
- engineer-profile validation;
- permanent candidate-only/non-authority assertions;
- forbidden `oc_graph` mutation strings;
- Ruff and `git diff --check`.

## Permanent non-authority

The service readiness and concept contracts report:

- `candidate_only=true`;
- `scientific_review_required=true`;
- `scientific_publication_authorized=false`;
- `production_deployment_authorized=false`;
- `knowledge_graph_mutation_authorized=false`.

## Explicit non-actions

No autonomous scientific publication, taxonomy activation, production deployment, merge, or production Knowledge Graph mutation is authorized by this build.
