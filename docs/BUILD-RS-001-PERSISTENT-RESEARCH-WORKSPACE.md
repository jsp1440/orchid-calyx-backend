# BUILD-RS-001 — Persistent Research Workspace

## Objective

Provide the first production-backed Research Station workspace without duplicating canonical taxonomy, documents, evidence, identity, or publication systems.

## Scope

- Owner-isolated research projects
- Optimistic project updates
- Archive and restore lifecycle
- Saved searches
- Research notes
- Canonical taxon, document, and evidence links
- Append-only workspace activity
- Standard Calyx owner-session/API-key authentication

## Architecture

The Research Station is an organizational layer over existing canonical Orchid Continuum stores. It does not create substitute taxonomy, document, evidence, Knowledge Graph, scientific-object, or publication systems.

Canonical references are validated against their owning stores before links are persisted.

## Persistence

Migration `migrations/101_research_workspace_foundation.sql` creates the additive `research_station` PostgreSQL schema and seven tables. The migration is idempotent, contains no destructive table operations, protects audit rows from update/delete, and revokes public table access.

## API

Routes are mounted below `/api/research/projects` and require an owner session or API key.

## Validation

- Focused service tests cover ownership isolation, lifecycle, optimistic updates, pagination, saved searches, notes, links, audit redaction, and migration safety.
- PostgreSQL migration validation remains required in CI before merge.
- No production database or deployment is modified by this pull request.
