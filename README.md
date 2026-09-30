# Calyx - Orchid Show Management System

Backend API for Calyx, powered by Orchid Continuum.

## Run Command

For Replit Deployments:
```bash
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-3000}
```

### Show Day profile

To run only orchid show operations (shows, entries, judging, QR tags, results,
volunteers), without the scientific and agent-automation layers:

```bash
uvicorn app.show_app:app --host 0.0.0.0 --port ${PORT:-3000}
```

Every `/api` route still needs `X-API-Key`. For a local rehearsal on SQLite, set
`CALYX_SHOW_CREATE_TABLES=1` to create the show tables on startup. Set
`CALYX_TAG_BASE_URL` to make tag QR codes link to a scan page (for example
`https://<frontend>/scan`); otherwise they encode the bare token. The show
endpoints added in this profile are:

- `GET /api/judging/events/{event_id}/tags`: a printable HTML sheet of entry tags, grouped by class (`?category_id=` for one class).
- `GET /api/judging/plants/{plant_id}/qr.svg`: one plant's QR code.
- `GET /api/judging/scan/{qr_token}`: resolves a scanned tag to its plant, class and scorecard progress.
- `GET /api/judging/events/{event_id}/class-results`: placements per class, from submitted scorecards only.

Blind judging events withhold exhibitor names from tags, scans and results.
Setting a show's `judging_locked` freezes all score writes.

## Environment Variables

### Release 1 checklist

Every variable Release 1 reads. The same list lives in `app/release_env.py` and
drives both checks below, and `tests/test_release1_env_readiness.py` fails if
this table and that list drift apart.

- `python scripts/preflight_release1_env.py` (add `--json` for JSON): env-only,
  no network. Prints `present`/`absent` per variable and exits 1 when a
  required variable (or its listed fallback) is absent. It never prints a
  value, a length or a hash.
- `GET /api/system/config-readiness` (owner session only; members get 403,
  anonymous callers 401, the backend API key alone gets 403): the same report
  as JSON, with presence booleans and the required flag only.

"Present" means set to a non-blank value. Neither check validates a value; a
wrong value that is present still reports present.

| Variable | Required | Default | Purpose | When missing |
|----------|----------|---------|---------|--------------|
| `DATABASE_URL` | **Yes** | unset (SQLite `sqlite:///./calyx.db`) | Production PostgreSQL connection string (app/database.py, evidence feedback, runtime, literature). | Show data falls back to a local SQLite file (not durable on Render); evidence feedback falls back to the file store and reports itself non-durable; PostgreSQL-backed routes are unavailable. |
| `PGHOST` | No | unset | Legacy Replit PostgreSQL host. When set it takes precedence over DATABASE_URL for show data (app/database.py), together with PGUSER/PGPASSWORD/PGDATABASE/PGPORT. | Nothing; DATABASE_URL is used. Leave unset on Render unless show data deliberately lives elsewhere. |
| `CALYX_EVIDENCE_FEEDBACK_ROOT` | No | `data/evidence_feedback` | File-store directory for evidence feedback, used only when DATABASE_URL is unset (app/evidence_feedback/routes.py). | With no DATABASE_URL either, feedback is written to the default local directory and every response carries the NON-DURABLE warning. |
| `CALYX_API_KEY` | **Yes** | unset | Service credential expected in the `X-API-Key` header (app/security.py). | Every X-API-Key-protected route returns 401 `API key authentication is not configured`. |
| `CALYX_OWNER_ACCESS_CODE` | **Yes** | unset | Owner sign-in access code (app/security.py). | Owner sign-in returns 503 `Owner access is not configured`; no owner session can be issued. |
| `CALYX_OWNER_SESSION_SECRET` | **Yes** | unset | HMAC key that signs and verifies owner session tokens (app/security.py). | Owner session issuance returns 503 `Owner session signing is not configured`; owner-only routes stay 401/503. |
| `CALYX_OWNER_SESSION_TTL_SECONDS` | No | `3600` (clamped to 300..86400) | Owner session lifetime. | Default lifetime is used. |
| `CALYX_OWNER_COOKIE_SECURE` | No | true when `RENDER` is set, else false | Marks the owner session cookie Secure. | Derived from `RENDER`. |
| `CALYX_OWNER_COOKIE_SAMESITE` | No | `none` when the cookie is Secure, else `lax` | SameSite attribute of the owner session cookie; invalid values become `lax`. | Derived default is used. |
| `ORCHID_JUDGE_ADMIN_KEY` | No | unset | Legacy `X-Orchid-Admin-Key` for judging admin routes (app/security.py `require_admin`). | Routes guarded by `require_admin` return 503 `Admin authentication is not configured`. |
| `OC_SUPABASE_URL` | **Yes** (or `OCU_SUPABASE_URL`) | unset | Supabase project URL used to verify member bearer tokens (app/member_auth.py). | Member tokens cannot be verified, so member reads and member feedback are refused; owner and API-key access are unaffected. |
| `OCU_SUPABASE_URL` | No | unset | Fallback for OC_SUPABASE_URL (read only when OC_SUPABASE_URL is blank). | Nothing when OC_SUPABASE_URL is set. |
| `OC_SUPABASE_ANON_KEY` | **Yes** (or `OCU_SUPABASE_ANON_KEY`) | unset | Supabase anonymous (publishable) key sent when verifying member tokens (app/member_auth.py). | Member tokens cannot be verified, so member reads and member feedback are refused. |
| `OCU_SUPABASE_ANON_KEY` | No | unset | Fallback for OC_SUPABASE_ANON_KEY (read only when OC_SUPABASE_ANON_KEY is blank). | Nothing when OC_SUPABASE_ANON_KEY is set. |
| `OC_MEMBER_READS_ENABLED` | No | unset = enabled | Kill switch for member read access; only `1/true/yes/on` enable it once set (app/member_auth.py). | Unset keeps member reads on; any other set value turns them off and members fall back to owner-path 401s. |
| `CALYX_EVIDENCE_FEEDBACK_ACTOR_REF_SECRET` | No | unset (falls back to CALYX_OWNER_SESSION_SECRET, domain-separated) | HMAC key for opaque submitter/reviewer references in the review queue (app/evidence_feedback/review.py). | Falls back to the owner session secret; with neither set, references read `actor-unavailable` instead of any identity. |
| `CORS_ALLOW_ORIGIN` | No | unset (built-in Mission Control origins only) | Comma-separated extra browser origins allowed on credentialed routes (app/routers/health.py); `*` is ignored. | Only the built-in origins are allowed; other frontends' browser calls fail CORS. |
| `CORS_ALLOW_ORIGINS` | No | `*` | Allowed origins for the Show Day profile only (app/show_app.py). | All origins are allowed on the Show Day profile. |
| `RENDER` | No | set by Render | Platform marker; defaults the owner cookie to Secure. | Owner cookie is not Secure unless CALYX_OWNER_COOKIE_SECURE says so. |
| `CALYX_TAG_BASE_URL` | No | unset | Frontend scan-page URL encoded into entry-tag QR codes (app/routers/show_day.py). | QR codes encode the bare tag token instead of a scan link. |
| `NO_API_MODE` | No | `true` | Global paid-provider brake; anything other than `false` blocks live provider calls (Firecrawl provider and runtime). | Treated as `true`: paid provider calls are blocked. |
| `PROVIDER_AUTHORIZED` | No | `false` | Second explicit authorization required, with NO_API_MODE=false, before any live Firecrawl call. | Treated as `false`: live Firecrawl calls are blocked (`PROVIDER_NOT_AUTHORIZED`). |
| `FIRECRAWL_ENABLED` | No | `false` | Enables the Firecrawl literature pilot. | Pilot is disabled (`FIRECRAWL_DISABLED`). |
| `FIRECRAWL_KILL_SWITCH` | No | `false` | Any value other than `false` stops the pilot. | Pilot is not killed by this switch. |
| `FIRECRAWL_DRY_RUN` | No | `true` | Fixture-only execution; no network. | Dry run: live calls are refused. |
| `FIRECRAWL_PILOT_MODE` | No | `true` | Restricts live execution to the pilot issue and genus. | Pilot restrictions stay on. |
| `FIRECRAWL_API_KEY` | No | unset | Firecrawl credential for live acquisition. | Live acquisition is blocked (`FIRECRAWL_KEY_UNAVAILABLE`). |
| `FIRECRAWL_APPROVED_DOMAINS` | No | empty | Comma-separated allowlist of acquisition domains. | No domain is approved, so nothing is fetched. |
| `FIRECRAWL_MAX_SEARCHES_PER_TASK` | No | `1` | Per-task search cap. | Default cap. |
| `FIRECRAWL_MAX_DOCUMENTS` | No | `2` | Per-task document cap. | Default cap. |
| `FIRECRAWL_RETRY_CAP` | No | `2` | Retry ceiling per call. | Default cap. |
| `FIRECRAWL_BACKOFF_SECONDS` | No | `1` | Retry backoff. | Default backoff. |
| `FIRECRAWL_MAX_CALL_COST_USD` | No | `0` | Worst-case reserved cost per call; must be > 0 for live runs. | Zero: live execution is blocked. |
| `FIRECRAWL_DAILY_BUDGET_USD` | No | `0` | Daily spend ceiling; must be > 0 for live runs. | Zero: live execution is blocked. |
| `FIRECRAWL_DAILY_CREDIT_CAP` | No | `25` | Daily provider-credit ceiling. | Default cap. |
| `FIRECRAWL_PILOT_GENUS` | No | `Paphiopedilum` | Genus the pilot is scoped to. | Default genus. |
| `FIRECRAWL_PILOT_ISSUE_NUMBER` | No | empty | GitHub issue a live pilot run must reference. | Live pilot runs are refused (`LIVE_PILOT_ISSUE_SCOPE_REQUIRED`); dry runs are unaffected. |
| `FIRECRAWL_REQUIRED_PREDICATES` | No | empty | Comma-separated predicate scope for the acquisition-coverage audit (app/literature_extraction/routes.py). | The coverage audit runs without a predicate filter. |

`PGUSER`, `PGPASSWORD`, `PGDATABASE` and `PGPORT` are read only together with
`PGHOST`. Variables read elsewhere in `app/` for agent providers, harvesters,
Zenodo, Google Drive/Gmail and the engineering/orchestrator lanes are not part
of the Release 1 checklist.

### Other variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PORT` | No | `3000` | Port to bind (set by the host in deployments) |
| `CALYX_SHOW_CREATE_TABLES` | No | unset | Show Day profile only: `1` creates the show tables on startup for a local SQLite rehearsal |
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
