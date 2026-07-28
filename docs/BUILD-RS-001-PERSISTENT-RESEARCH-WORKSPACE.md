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

Run:

```text
python -m pytest -q tests/test_build_rs_001_research_workspace.py tests/test_owner_session_cors_repair.py
python -m ruff check app/research_workspace tests/test_build_rs_001_research_workspace.py
python -m compileall app/research_workspace
```

Run a secret-pattern scan on the changed files before commit. PostgreSQL
migration integration requires an explicitly disposable `TEST_DATABASE_URL`;
production must never be used for migration tests.

## Rollback

Application rollback is removal of the router include and deployment of the prior
backend version. The additive schema should remain in place to preserve projects and
audit history. A later separately reviewed migration may retire it only after data
retention/export decisions are complete.
