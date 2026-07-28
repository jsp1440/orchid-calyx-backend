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

- Final focused branch diff versus `main` is limited to:
  - `app/research_workspace/models.py`
  - `app/research_workspace/routes.py`
  - `app/research_workspace/service.py`
  - `docs/BUILD-RS-001-PERSISTENT-RESEARCH-WORKSPACE.md`
  - `tests/test_build_rs_001_research_workspace.py`
- Focused service tests cover ownership isolation, lifecycle, optimistic updates, pagination, saved searches, notes, links, audit redaction, and migration safety.
- The additive migration remains at `migrations/101_research_workspace_foundation.sql` and is already present on current `main`.
- Minimal router registration remains in `app/main.py` and is already present on current `main`.
- GitHub Actions `BUILD-088E Validation` run `194` currently finishes as
  `action_required` with `0` jobs and no failed-job logs; the same no-job
  `action_required` pattern affects multiple legacy pull-request validation
  workflows on this Copilot-updated branch, so no workflow weakening was
  applied from BUILD-RS-001.
- PostgreSQL migration validation remains required in CI before merge.
- No production database or deployment is modified by this pull request.

Run:

```text
python3 -m pytest -q tests/test_build_rs_001_research_workspace.py
python3 -m pytest -q tests/test_build_063_owner_auth.py tests/test_owner_session_cors_repair.py
python3 -m ruff check app/research_workspace tests/test_build_rs_001_research_workspace.py
python3 -m compileall app/research_workspace
```

Current local results:

- `python3 -m pytest -q tests/test_build_rs_001_research_workspace.py` → `7 passed`
- `python3 -m pytest -q tests/test_build_063_owner_auth.py tests/test_owner_session_cors_repair.py`
  → `1 failed, 30 passed`
  (`tests/test_build_063_owner_auth.py::test_runner_authenticated_start_includes_cors_headers`
  receives `405` from `POST /api/runner/start`, and the same failure reproduces
  on `origin/main`)
- `python3 -m pytest -q tests/test_owner_session_cors_repair.py` → `8 passed`
- `python3 -m ruff check app/research_workspace tests/test_build_rs_001_research_workspace.py` → passed
- `python3 -m compileall app/research_workspace` → passed
- secret scan on `app/research_workspace/models.py`,
  `app/research_workspace/routes.py`, `app/research_workspace/service.py`,
  `docs/BUILD-RS-001-PERSISTENT-RESEARCH-WORKSPACE.md`, and
  `tests/test_build_rs_001_research_workspace.py` → clean
- disposable PostgreSQL validation → applied
  `migrations/101_research_workspace_foundation.sql` twice against `postgres:16`,
  confirmed `tables=7`, `distinct_triggers=1`, and blocked audit-event mutation
  with `research workspace audit events are append-only`

Run a secret-pattern scan on the changed files before commit. PostgreSQL
migration integration requires an explicitly disposable `TEST_DATABASE_URL`;
production must never be used for migration tests.

## Rollback

Application rollback is removal of the router include and deployment of the prior
backend version. The additive schema should remain in place to preserve projects and
audit history. A later separately reviewed migration may retire it only after data
retention/export decisions are complete.
