# Calyx - Orchid Show Management System

Backend API for Calyx, powered by Orchid Continuum.

## Run Command

For Replit Deployments:
```bash
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-3000}
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | No | `sqlite:///./calyx.db` | PostgreSQL connection string for production |
| `PORT` | No | `3000` | Port to bind (set by Replit in deployments) |
| `CORS_ALLOW_ORIGINS` | No | `*` | Comma-separated allowed origins, or `*` for all |
| `CALYX_API_KEY` | No | None | If set, requires `X-API-Key` header for `/api/*` routes |
| `AUTO_CREATE_TABLES` | No | `1` | Set to `0` to disable auto table creation |
| `LITERATURE_EXTRACTION_ROOT` | No | `runtime/literature_extraction` | Directory holding literature-extraction runs and receipts. Read by `app/literature_extraction/routes.py`, `app/reasoning_ledger/operational_service.py`, `runtime/graph_pipeline_readiness.py`, `runtime/calyx_core_certification.py`. On a host without a persistent disk the default is ephemeral. |
| `SOURCE_DATE_EPOCH` | No | unset | Integer Unix timestamp that pins taxonomy-preflight artifact timestamps for reproducible builds (`runtime/taxonomy_preflight_governance.py`; set and cleared by `runtime/taxonomy_preflight_reproducibility.py`). A non-integer value is rejected. |

## Render deployment contract

Render is the deployment target (service `orchid-calyx-backend`,
`https://orchid-calyx-backend.onrender.com`, per the Brain
`config/infrastructure_registry.json`). This repository ships no `render.yaml`,
`Dockerfile` or `Procfile`: the service's build and start commands live in the
Render dashboard and cannot be verified from the repository. What the
repository supports is:

- Start command: `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-3000}`
  (Render supplies `PORT`).
- Health check path: `/health` (`app/routers/health.py`), returning
  `{"status":"ok"}`. The Brain registry declares the same `health_path`; use it
  for infrastructure checks rather than `/api/runtime/heartbeat`.
- Dependency profile: `requirements.txt` is the base runtime;
  `requirements-scientific.txt` includes it and pins `scipy==1.18.0`, the
  version `runtime/scientific_runtime_readiness.py` requires before the
  mean-CI scientific surface reports itself ready. A build from
  `requirements.txt` alone drifts to the newest scipy and reports
  `scipy_compatible: false`.
- `DATABASE_URL` must point at the production PostgreSQL (Neon) database;
  the SQLite default is for local development only.

## API Endpoints

### Health
```bash
curl https://your-app.replit.app/health
# {"status":"ok"}
```

### Tile Registry
```bash
curl https://your-app.replit.app/api/tiles/registry
```

**Response Schema:**
```json
{
  "version": "1.0",
  "tiles": [
    {
      "id": "string",
      "title": "string",
      "route": "string",
      "role_visibility": ["admin", "exhibitor", "volunteer", "judge"],
      "status": "active"
    }
  ]
}
```

### Shows CRUD
```bash
# List shows
curl https://your-app.replit.app/api/shows

# Create show
curl -X POST https://your-app.replit.app/api/shows \
  -H "Content-Type: application/json" \
  -d '{"name": "Spring Show 2026", "start_date": "2026-03-15", "location": "Garden Center"}'

# Get show
curl https://your-app.replit.app/api/shows/{show_id}

# Update show
curl -X PATCH https://your-app.replit.app/api/shows/{show_id} \
  -H "Content-Type: application/json" \
  -d '{"location": "New Location"}'

# Delete show
curl -X DELETE https://your-app.replit.app/api/shows/{show_id}
```

### Entries CRUD
```bash
# List entries (optionally filter by show_id)
curl https://your-app.replit.app/api/entries?show_id={show_id}

# Create entry
curl -X POST https://your-app.replit.app/api/entries \
  -H "Content-Type: application/json" \
  -d '{"show_id": "...", "exhibitor_name": "John Doe", "plant_name": "Cattleya", "class_code": "A1"}'
```

### Volunteer Tasks CRUD
```bash
# List tasks
curl https://your-app.replit.app/api/volunteer-tasks?show_id={show_id}

# Create task
curl -X POST https://your-app.replit.app/api/volunteer-tasks \
  -H "Content-Type: application/json" \
  -d '{"show_id": "...", "title": "Setup tables", "assigned_to": "Jane"}'
```

### Awards CRUD
```bash
# List awards
curl https://your-app.replit.app/api/awards?entry_id={entry_id}

# Create award
curl -X POST https://your-app.replit.app/api/awards \
  -H "Content-Type: application/json" \
  -d '{"entry_id": "...", "award_name": "Best in Show", "level": "1st"}'
```

## With API Key Authentication

If `CALYX_API_KEY` is set:
```bash
curl https://your-app.replit.app/api/shows \
  -H "X-API-Key: your-api-key-here"
```

## Interactive Docs

Visit `/docs` for Swagger UI documentation.
