# BUILD-049 - Calyx Harvester Command Center and Adaptive Source Router

## Principle

"Any scientific entity or relationship may become the center of inquiry and may generate evidence-acquisition missions. Harvesters are governed scientific workers, not unattended scraping scripts."

## Architecture

BUILD-049 extends the existing Calyx backend instead of creating a parallel runtime. The implementation adds `runtime.harvester_control` as the governed control-plane service and `app.routers.harvesters` as the authenticated API surface. The route family is mounted through the existing `app.routers.health` router because that router is already included by `app.main`; this avoids a large remote rewrite of `app/main.py` while preserving existing routes.

## Database Objects

Migration: `migrations/BUILD-049-harvester-command-center.sql`

- `oc_admin.harvester_registry`
- `oc_admin.harvester_runs`
- `oc_admin.harvester_target_proposals`

The migration is idempotent and seeds known harvesters with unknown historical telemetry rather than fabricated zero values.

## API Routes

- `GET /api/harvesters`
- `GET /api/harvesters/{harvester_id}`
- `GET /api/harvesters/{harvester_id}/runs`
- `POST /api/harvesters/{harvester_id}/run-once`
- `POST /api/harvesters/{harvester_id}/pause`
- `POST /api/harvesters/{harvester_id}/resume`
- `POST /api/harvesters/{harvester_id}/retire`
- `POST /api/harvesters/{harvester_id}/restore`
- `POST /api/harvesters/{harvester_id}/target-proposals`
- `POST /api/harvesters/{harvester_id}/target-proposals/{proposal_id}/approve`
- `POST /api/harvesters/{harvester_id}/target-proposals/{proposal_id}/reject`
- `PATCH /api/harvesters/{harvester_id}/schedule`
- `GET /api/harvesters/{harvester_id}/recommendation`
- `POST /api/harvesters/{harvester_id}/reassess`

State-changing routes depend on the repository's `X-API-Key` backend API-key dependency. No browser-side unlock is treated as authorization.

## State Machine

Supported states: `active`, `paused`, `run_once`, `draining`, `exhausted`, `needs_review`, `redirect_pending`, `failed`, and `retired`.

Retirement preserves run history. Restoration is policy-gated. Target changes enter `redirect_pending` until approved or rejected.

## Constitutional Safety

The control plane evaluates actions through the BUILD-034 constitutional orchestrator. Low-risk operations such as reassessment and run-once are scoped to registered non-destructive jobs. Target changes, schedule changes, retirement, and restoration are high-risk policy actions and may require review even if the caller requests a high autonomy level.

## Recommendation Algorithm

The adaptive source router considers novelty rate, duplicate rate, error rate, freshness, unchanged checkpoints, exhaustion score, downstream relationship yield, and unknown telemetry. Unknown values remain unknown. Duplicate-heavy sources recommend reduced frequency; high exhaustion recommends retirement as exhausted; error-heavy sources recommend review.

## Scientific Target Contract

`ScientificTarget` supports taxon, geography, elevation band, habitat, pollinator group, mycorrhizal group, literature topic/query, publication date range, occurrence freshness window, image/media gap, conservation status gap, relationship-gap query, and future entity references.

## Seeded Harvesters

iNaturalist, GBIF, World Plants / Hassler, EOL / TraitBank, image/media harvesters, literature harvesters, mycorrhizal harvesters, climate/elevation enrichment, and conservation enrichment.

## Deployment

Backend deployment is required after merge. Apply the migration before relying on persistent registry/run/proposal storage. Frontend deployment is required only after the companion Mission Control UI changes are merged.

## Rollback

Disable frontend action controls first. Revert the backend router include from `app/routers/health.py` to remove action routes. The migration is additive; do not drop tables during rollback unless explicitly approved because run history and proposals are audit records.

## Known Limitations

This build introduces the governed contract and in-process implementation path. Production persistence must be smoke-tested against the deployed database. PR #18 and PR #19 contain foundational constitutional/autonomous runtime work and should be reconciled before merge if their route or schema changes overlap.

## Dynamic Cognitive Knowledge Map

Future knowledge-graph-driven missions can use the target contract's `entity_ref` to center any entity or relationship node and generate evidence-acquisition missions with provenance, approval, and audit records.
