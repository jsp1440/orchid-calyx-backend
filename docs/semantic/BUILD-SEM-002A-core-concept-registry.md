# BUILD-SEM-002A — Core Concept Registry

Status: implementation for Epic #123 / Issue #124

## Purpose

BUILD-SEM-002A establishes stable semantic identity without implementing lexical or integration layers. It adds `ConceptScheme`, `ConceptRelease`, and `Concept` persistence; a lifecycle service; an additive ontology-term adapter; and one authenticated read-only endpoint.

## Persistence

Migration `migrations/102a_core_concept_registry.sql` creates the isolated `oc_concepts` schema:

- `concept_schemes`: scheme identity, authority, stewardship, review state, and timestamps;
- `concept_releases`: scheme-scoped version and release metadata;
- `concepts`: immutable UUID/URI identity, lifecycle, review state, stewardship, release association, timestamps, and supersession;
- `ontology_term_concepts`: one-to-one compatibility bridge to existing ontology terms;
- `concept_audit_events`: append-only records of concept creation, transition, and adaptation.

All statements are additive. The migration does not alter, update, delete, truncate, deprecate, or replace any `oc_ontology` object.

## Stable identity

Concept identifiers are opaque UUIDs. The only valid URI form is:

`https://id.orchidcontinuum.org/concept/{uuid}`

The database checks the URI against the UUID. A trigger prohibits update of either identity field and prohibits concept deletion. Concepts are retained through `DEPRECATED` or `SUPERSEDED` lifecycle states. Supersession references an active replacement concept in the same scheme.

## Lifecycle and governance

Concept lifecycle states:

- `DRAFT`;
- `ACTIVE`;
- `DEPRECATED`;
- `SUPERSEDED`.

Transitions are forward-only. Activation marks review as approved. Supersession requires a distinct, active replacement in the same scheme. Review state, steward, `created_at`, and `revised_at` are explicit fields. A concept can optionally reference a scheme-compatible release.

## Compatibility

`OntologyTermConceptAdapter` creates a new concept and records a mapping for an existing `oc_ontology.ontology_terms` row in one transaction. Repeated adaptation returns the prior concept, making the path idempotent. It never modifies the source ontology term. Existing ontology models, repositories, services, routes, and migration remain unchanged.

There is no automatic bulk backfill in this build. Operators can adopt the adapter in a separately approved migration/backfill build after choosing a ConceptScheme and stewardship policy.

## API

`GET /api/concepts/{id-or-uri}` is authenticated with the existing owner-session/API-key dependency. It accepts either the UUID or canonical URI and returns the concept with scheme and optional release metadata.

No create, update, transition, search, label, mapping, or deletion endpoint is exposed.

## Validation

The focused tests cover:

- canonical URI generation and identity immutability;
- identifier non-reuse;
- lifecycle and supersession rules;
- scheme/release association and metadata;
- idempotent ontology compatibility;
- authentication and retrieval by UUID/URI;
- migration additivity;
- continued presence of existing ontology API routes.

The static migration validator checks required tables, identity triggers, release consistency, and absence of destructive or ontology-altering statements.

The CI PostgreSQL validator applies migrations 076a, 076b, 077, and 102a to an ephemeral PostgreSQL 16 service, reapplies 102a, exercises activation and supersession, proves UUID/URI updates and deletion are rejected, and confirms legacy ontology tables remain present.

## Known limitations

- no labels, synonyms, definitions, languages, search, relationships, or external mappings;
- no write API;
- no automatic backfill;
- no Calyx, Knowledge Graph, literature, or Species Dossier integration;
- release publishing workflow is not implemented;
- PostgreSQL remains the authoritative persistence target.
