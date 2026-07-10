# BUILD-048 — Scientific Integration Coordinator

## Purpose

BUILD-048 turns the BUILD-047 science-priority scaffold into a first safe integration coordinator. It does not yet mutate the database or call external scientific APIs. It exposes the scientific operations plan as backend API endpoints so Calyx, the control panel, and future frontend work can see what scientific systems need attention first.

## Implemented

- Expanded `runtime/science_registry.py` from a priority scaffold into a non-destructive scientific integration coordinator.
- Added a dataset registry for major Orchid Continuum sources:
  - World Plants orchid taxonomy
  - GBIF occurrences
  - iNaturalist observations and living images
  - EOL TraitBank
  - Zenodo orchid pollination dataset
  - GloBI interactions
  - literature extraction tables
  - mycorrhizal relationship data
  - climate/elevation layers
- Added coverage-gap reporting for scientific departments.
- Added safe work-item generation for scientific missions.
- Added harvester-readiness reporting.
- Added dossier candidate queues for species, pollinators, and fungi.
- Added new science API endpoints in `runtime/router_fastapi.py`.

## New API endpoints

After backend deployment, these endpoints should be available:

- `GET /api/science/status`
- `GET /api/science/summary`
- `GET /api/science/departments`
- `GET /api/science/departments/{department_id}`
- `GET /api/science/missions`
- `GET /api/science/datasets`
- `GET /api/science/gaps`
- `GET /api/science/harvesters`
- `GET /api/science/dossiers`
- `POST /api/science/seed-missions`
- `POST /api/science/audit/pollinators`
- `POST /api/science/audit/mycorrhiza`
- `POST /api/science/audit/literature`
- `POST /api/science/audit/traits`
- `POST /api/science/audit/elevation`
- `POST /api/science/audit/climate`
- `POST /api/science/audit/harvesters`
- `POST /api/science/audit/dossiers`

## Safety model

BUILD-048 is intentionally conservative:

- no destructive actions
- no external mutations
- no unsupported biological claims promoted as facts
- no automatic schedule changes
- no database writes
- no frontend deploy

All scientific work is represented as audit-only, provenance-required, needs-review work.

## Why this matters

This build moves Calyx from merely knowing that science is the priority to being able to report scientific system status and create safe next work items. It sets up the next phase: read-only live database coverage queries for pollinators, fungi, literature, traits, images, Atlas, climate, and elevation.

## Post-deploy smoke test

After backend deployment, verify:

1. `GET /`
2. `GET /docs`
3. `GET /api/science/status`
4. `GET /api/science/datasets`
5. `GET /api/science/gaps`
6. `GET /api/science/harvesters`
7. `GET /api/science/dossiers`
8. `POST /api/science/audit/pollinators`
9. `POST /api/science/audit/mycorrhiza`
10. `GET /api/runner/autonomous-status`

Expected result: FastAPI starts, science endpoints respond, runtime endpoints still exist, and outputs show no destructive actions or promoted unsupported claims.

## Frontend deployment

Frontend deployment is not required. This is a backend-only API/coordinator build.

## Backend deployment

Backend deployment is required after merge.
