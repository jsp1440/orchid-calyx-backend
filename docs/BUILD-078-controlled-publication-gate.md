# BUILD-078 Controlled Knowledge Graph Publication Gate

BUILD-078 adds an explicit, authenticated publication layer between BUILD-077 readiness and the canonical knowledge graph.

## Contract

- Publication is never automatic.
- `/api/publication/dry-run` is read-only for `oc_graph`.
- `/api/publication/publish` requires an authenticated owner/API-key caller, a human approval reference, and a publication authority.
- Every publish request re-plans and revalidates eligibility before graph writes.
- Taxonomy terms require an existing canonical taxon attachment such as `canonical_taxon_id` or `world_plants_id`.
- Unknown graph node or edge vocabulary is blocked, not invented.
- Canonical graph writes are transactional and guarded by the existing schema-scoped PostgreSQL advisory publication lock.
- Rollback is represented by supersession/rollback metadata. It does not delete canonical graph rows.
- No external API calls are made by the publication service.

## Schema

The additive migration `migrations/078_controlled_publication_gate.sql` creates `oc_publication` only:

- `publication_runs`
- `publication_items`
- `publication_decisions`
- `publication_conflicts`
- `publication_audit_events`
- `publication_rollbacks`

The migration does not alter `oc_graph` or taxonomy tables. It adds indexes for run lookup, candidate/item lookup, canonical key lookup, unresolved conflicts, and audit inspection. A database trigger rejects invalid publication item state transitions.

## API

- `POST /api/publication/dry-run`
- `POST /api/publication/publish`
- `POST /api/publication/runs/{run_id}/rollback`

All routes use the existing `verify_owner_or_api_key` dependency.

## Validation

Focused local tests cover dry-run immutability, taxonomy attachment blockers, human approval enforcement, idempotent publish behavior, rollback metadata, route auth, and additive migration checks.

The GitHub Actions workflow `.github/workflows/build-078-postgres-validation.yml` runs `scripts/build_078_postgres_validation.py` against `DATABASE_URL`. The script applies BUILD-076A, 076B, 077, and 078 migrations, seeds controlled validation records, exercises dry-run and publish, verifies idempotency, checks audit records, and confirms taxonomy table row counts remain unchanged.
