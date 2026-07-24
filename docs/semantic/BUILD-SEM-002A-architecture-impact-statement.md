# BUILD-SEM-002A — Architecture Impact Statement

References: BUILD-SEM-001 Semantic Knowledge Architecture, Epic #123, Issue #124

## Decision

Introduce an additive Core Concept Registry as a new bounded module and PostgreSQL schema. The registry owns only stable concept identity, scheme/release association, lifecycle, review state, stewardship, timestamps, and supersession.

## Alignment with BUILD-SEM-001

BUILD-SEM-001 identified stable concept identity as the prerequisite for lexical knowledge, mappings, annotation, retrieval, Knowledge Graph projection, workbench delivery, and Calyx grounding. BUILD-SEM-002A implements that prerequisite while deliberately stopping before those later layers.

The design follows the BUILD-SEM-001 principles that:

- concept identity is independent of labels and database row numbers;
- identifiers are opaque, permanent, and never reused;
- canonical changes are governed and reviewable;
- deprecated concepts remain resolvable;
- existing ontology capability should be extended through adapters rather than rewritten.

## Runtime impact

One authenticated read-only route is mounted at `/api/concepts/{id-or-uri}`. No existing route, request schema, response schema, service, or database object changes. No automatic backfill or background task runs. Existing ontology runtime behavior is preserved.

## Data impact

The migration creates only new objects under `oc_concepts`. Foreign keys read existing ontology term identity for the optional adapter mapping, but no ontology table is altered. Concept deletion is prohibited; lifecycle changes preserve history. Release association is validated to remain within the concept's scheme.

## Security and governance impact

The route reuses the established owner-session/API-key authentication and Mission Control CORS dependency. There are no public or write endpoints. Internal service writes require explicit stewardship and actor inputs, and mutations append audit events.

## Compatibility and reversibility

Applications that do not use `/api/concepts` are unaffected. The adapter is opt-in and idempotent. Because the migration is additive and no existing data is rewritten, deployment can leave the new schema unused without changing legacy behavior. Removing created data is intentionally not part of runtime rollback because identifiers must not be reused; operational rollback should disable consumers while preserving registry history.

## Deferred architecture

Per Issue #124, this build does not implement labels, synonyms, definitions, multilingual support, search, typed relationships, external mappings, Calyx, Knowledge Graph, literature, or Species Dossier integration. Those remain future builds under Epic #123.
