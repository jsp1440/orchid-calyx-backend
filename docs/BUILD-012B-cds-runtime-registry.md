# BUILD-012B — CDS Runtime Registry

BUILD-012B turns the Calyx Development Suite v2 package into live backend configuration and API endpoints.

## Added

- `config/cds_module_registry.json`
- `config/cds_dashboard.json`
- `config/cds_priorities.csv`
- `runtime/cds_loader.py`
- `runtime/cds_router.py`

## API endpoints

- `GET /api/cds/summary`
- `GET /api/cds/modules`
- `GET /api/cds/modules/{module_id}`
- `GET /api/cds/dashboard`
- `GET /api/cds/priorities`
- `POST /api/cds/reload`

## Purpose

CDS becomes Calyx's live operating registry. Instead of treating the CDS package as documentation only, Calyx can now report its modules, priorities, domains, and dashboard metadata through API endpoints.

## Acceptance check after deploy

1. Open `/docs` and confirm the `Calyx Development Suite` tag is present.
2. Execute `GET /api/cds/summary`.
3. Execute `GET /api/cds/modules`.
4. Execute `GET /api/cds/dashboard`.
5. Confirm `DatabaseInspector` is present and marked `live-ready`.

## Next build

BUILD-012C should connect the live database inspector and runtime engine state to the CDS dashboard so module status is no longer registry-only.
