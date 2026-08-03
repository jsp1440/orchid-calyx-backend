# Orchid Continuum Parallel Contract v1

## Repository ownership

- **Orchid-Continuum-Brain**: governed reasoning, scores, educational/design recommendations, uncertainty explanations, validation pathways.
- **orchid-calyx-backend**: canonical taxonomy, evidence, Knowledge Graph, persistence, authentication, review, publication, versioned APIs.
- **orchid-continuum-frontend**: presentation, interaction, accessibility, observation capture, typed API consumption.

## Versioned backend capability surface

Planned additive contracts:

- `GET /app-center/v1/capabilities`
- `GET /app-center/v1/homepage`
- `GET /app-center/v1/matrix/{taxon_id}`
- `GET /app-center/v1/matrix/compare?left=...&right=...`
- `POST /app-center/v1/identification/sessions`
- `POST /app-center/v1/identification/sessions/{session_id}/observations`
- `GET /app-center/v1/identification/sessions/{session_id}/candidates`
- `GET /brain/context/{capability}`
- `POST /brain/recommendations`

Exact paths may be adapted to existing router conventions while preserving the semantic contracts.

## Shared capability domains

1. `homepage_intelligence`
2. `relationship_matrix`
3. `orchid_identification`
4. `education_intelligence`
5. `design_intelligence`
6. `scientific_reasoning`
7. `knowledge_graph_context`

## Required response semantics

Every scientific response must preserve:

- schema and provider version;
- canonical entity identifiers;
- availability state;
- evidence and provenance references;
- attribute-level confidence;
- uncertainty and contradictions;
- freshness and source versions;
- deterministic ordering;
- approval/publication boundaries.

## Relationship Matrix dimensions

- taxonomy
- morphology
- ecology
- geography
- phenology
- pollinator
- mycorrhiza
- conservation
- cultivation
- literature
- graph_evidence

Missing evidence is `unavailable`, never a fabricated zero. Pairwise aggregates must retain weights, rule version, evidence contributions, and missing-data treatment.

## Orchid identification states

- `observation_incomplete`
- `candidate_suggestions`
- `ambiguous`
- `requires_expert_review`
- `verified_external_identity`

Candidate ranking must separate supporting observations, conflicts, missing observations, and next-best observation prompts. Machine suggestion is never canonical identity.

## Homepage document

The homepage response should support ordered semantic sections for mission, featured genus/species, evolution, relationships, species exploration, conservation hotspots, education, research, and current Continuum activity. Missing subsystems return explicit degraded sections rather than failing the whole document.

## Brain handoff

Backend supplies canonical IDs, bounded evidence/context, source versions, and constraints. Brain returns governed recommendations and scores. Backend validates identities, stores approved artifacts, and enforces review/publication gates.

## Governance

No automatic scientific publication, merge, deployment, migration, canonical promotion, or production mutation. No private chain-of-thought storage.
