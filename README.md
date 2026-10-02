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

The variables the Release 1 journeys depend on: owner, member and API-key
authentication, storage, evidence feedback, show day, member Matrix
identification, generative-turn entitlements, public writes, release
identity, the autonomous runtime switches and the NO-API/Firecrawl brakes.
The list lives in `app/release_env.py` and drives both checks below.

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
| `DATABASE_URL` | **Yes** | unset (SQLite `sqlite:///./calyx.db`) | Production PostgreSQL connection string (app/database.py, evidence feedback, runtime, literature). | Show data falls back to a local SQLite file (not durable on Render); evidence feedback falls back to the local file store; routes that need PostgreSQL, such as the Mission Control review APIs, return 503. |
| `PGHOST` | No | unset | Legacy Replit PostgreSQL host. When set it takes precedence over DATABASE_URL for show data (app/database.py), together with PGUSER/PGPASSWORD/PGDATABASE/PGPORT. | Nothing; DATABASE_URL is used. Leave unset on Render unless show data deliberately lives elsewhere. |
| `PGUSER` | No | `postgres` | Read only together with PGHOST (app/database.py). | Default used when PGHOST is set; ignored otherwise. |
| `PGPASSWORD` | No | empty | Read only together with PGHOST (app/database.py). | Default used when PGHOST is set; ignored otherwise. |
| `PGDATABASE` | No | `postgres` | Read only together with PGHOST (app/database.py). | Default used when PGHOST is set; ignored otherwise. |
| `PGPORT` | No | `5432` | Read only together with PGHOST (app/database.py). | Default used when PGHOST is set; ignored otherwise. |
| `CALYX_EVIDENCE_FEEDBACK_ROOT` | No | `data/evidence_feedback` | File-store directory for evidence feedback, used only when DATABASE_URL is unset (app/evidence_feedback/routes.py). | With no DATABASE_URL either, feedback is written to the default local directory, which is lost on restart or redeploy. No response says so: the backend only logs a NON-DURABLE warning once at startup, and only when APP_ENV/ENVIRONMENT is `prod`/`production` or RENDER is truthy. |
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
| `CALYX_JUDGE_TOKEN_SECRET` | No | unset | HMAC key for per-judge credentials and judge-facing opaque handles (app/judge_auth.py); at least 32 characters and different from every other secret the app reads. | Judge access fails closed: credential issuance and every /api/judge-portal route return 503 `Judge authentication is not configured`. Rotating it invalidates every judge credential. |
| `JUDGE_AUTH_TRUSTED_PROXY_HOPS` | No | `0` | Number of trusted proxies that append to X-Forwarded-For; judge sign-in failures are counted against that hop's address (app/judge_auth.py). | Failures are counted against the direct peer address, so behind a proxy every judge device shares one per-client failure budget (a correct credential is never refused). |
| `JUDGE_AUTH_FAILURE_LIMIT_PER_CLIENT` | No | `50` | Failed judge sign-ins allowed per client address per window before failures answer 429 (app/judge_auth.py). | Default limit. |
| `JUDGE_AUTH_FAILURE_LIMIT_GLOBAL` | No | `500` | Failed judge sign-ins allowed across all clients per window before failures answer 429 (app/judge_auth.py). | Default limit. |
| `JUDGE_AUTH_FAILURE_WINDOW_SECONDS` | No | `300` | Window for the judge sign-in failure limits (minimum 1). | Default window. |
| `APP_ENV` | No | unset | `prod`/`production` marks a production-like host (read by evidence feedback and vision-lexicon activation, before ENVIRONMENT). | Production-likeness falls back to ENVIRONMENT, then to RENDER. |
| `ENVIRONMENT` | No | unset | Same as APP_ENV, read only when APP_ENV is blank. | Production-likeness falls back to RENDER. |
| `TEST_DATABASE_URL` | No | unset | Test/CI database. Several stores (for example app/persistence/state_repository.py, app/brain_mission, app/semantic) use it when DATABASE_URL is blank. | Nothing. Keep it unset in production so no store falls back to a test database. |
| `ADMIN_API_KEY` | No | unset (falls back to CALYX_API_KEY) | `X-Orchid-Admin-Key` for reference-document management (app/routers/reference_docs.py). | CALYX_API_KEY is used; with neither set, reference-doc admin routes refuse every request (503). |
| `CONSTITUENT_MANAGE_SECRET` | No | unset (falls back to CALYX_OWNER_SESSION_SECRET) | HMAC key for constituent preference-centre manage tokens (app/constituent_platform/service.py). | The owner session secret is used; with neither set, no manage token is issued and every token fails verification. |
| `MISSION_CONTROL_REVIEW_ALLOW_MEMORY` | No | `false` | Allows an in-memory, non-durable review queue when DATABASE_URL is blank (development only; app/review_api/dependencies.py). | Without DATABASE_URL the review APIs return 503 `REVIEW_DATABASE_NOT_CONFIGURED`. |
| `PUBLIC_WRITE_RATE_LIMIT` | No | `20` | Public write requests allowed per client per window (app/rate_limit.py); a non-integer uses the default. | Default limit. |
| `PUBLIC_WRITE_RATE_WINDOW_SECONDS` | No | `600` | Window for PUBLIC_WRITE_RATE_LIMIT (minimum 1); a non-integer uses the default. | Default window. |
| `PUBLIC_SITE_BASE_URL` | No | `https://orchidcontinuum.org` | Base URL of public species-dossier links (app/species_dossier/routes.py). | Default base URL. |
| `OC_MEMBER_MATRIX_IDENTIFICATION_ENABLED` | No | unset = enabled | Kill switch for member Matrix identification; once set only `1/true/yes/on` enable it (app/matrix_member_access.py). | Unset keeps it on; any other set value turns it off for members. |
| `OC_MEMBER_MATRIX_SESSIONS_PER_HOUR` | No | `30` | Per-member Matrix session creations per hour; non-positive or non-integer values use the default. | Default limit. |
| `OC_MEMBER_MATRIX_WRITES_PER_MINUTE` | No | `120` | Per-member Matrix session writes per minute; non-positive or non-integer values use the default. | Default limit. |
| `CALYX_GENERATIVE_ENTITLEMENT_MODE` | No | `owner_only` | Who may use generative Calyx turns (app/calyx_conversation/access_economics.py). | `owner_only`; an unrecognised value fails closed to `disabled`. |
| `CALYX_GENERATIVE_MEMBER_DAILY_TURNS` | No | `0` | Generative turns per member per day. | Zero turns per member. |
| `CALYX_GENERATIVE_DAILY_CEILING_TURNS` | No | unset | Daily ceiling on generative turns across members. | No ceiling value is configured. |
| `OCU_RELEASE_SHA` | No | unset | First choice for the deployed commit reported by the release-identity route (app/routers/release_identity.py). | The next name is tried; with none set, release identity reports `commit_sha: null`, `attested: false`. |
| `CALYX_DEPLOYED_COMMIT` | No | unset | Second choice for the deployed commit. | The next name is tried; with none set, release identity reports `commit_sha: null`, `attested: false`. |
| `RENDER_GIT_COMMIT` | No | unset | Third choice for the deployed commit (set by Render); also stamped on mission worker records. | The next name is tried; with none set, release identity reports `commit_sha: null`, `attested: false`. |
| `GIT_COMMIT` | No | unset | Fourth choice for the deployed commit. | The next name is tried; with none set, release identity reports `commit_sha: null`, `attested: false`. |
| `COMMIT_SHA` | No | unset | Fifth choice for the deployed commit. | The next name is tried; with none set, release identity reports `commit_sha: null`, `attested: false`. |
| `GIT_COMMIT_SHA` | No | unset | Fallback for RENDER_GIT_COMMIT on mission worker records (app/missions/repositories.py). | Worker records carry no commit. |
| `CALYX_AUTOLOOP_ENABLED` | No | unset | Any of the six runtime enable flags set true starts the autonomous runtime loop at startup (app/main.py); a flag set false blocks it. | The loop stays off unless another enable flag is true. |
| `OC_RUNNER_AUTOLOOP` | No | unset | Any of the six runtime enable flags set true starts the autonomous runtime loop at startup (app/main.py); a flag set false blocks it. | The loop stays off unless another enable flag is true. |
| `CALYX_RUNTIME_ENABLED` | No | unset | Any of the six runtime enable flags set true starts the autonomous runtime loop at startup (app/main.py); a flag set false blocks it. | The loop stays off unless another enable flag is true. |
| `AUTONOMOUS_RUNTIME_ENABLED` | No | unset | Any of the six runtime enable flags set true starts the autonomous runtime loop at startup (app/main.py); a flag set false blocks it. | The loop stays off unless another enable flag is true. |
| `RUNNER_ENABLED` | No | unset | Any of the six runtime enable flags set true starts the autonomous runtime loop at startup (app/main.py); a flag set false blocks it. | The loop stays off unless another enable flag is true. |
| `CALYX_AUTONOMOUS_ENABLED` | No | unset | Any of the six runtime enable flags set true starts the autonomous runtime loop at startup (app/main.py); a flag set false blocks it. | The loop stays off unless another enable flag is true. |
| `CALYX_AUTONOMOUS_DISABLED` | No | unset | Set true, keeps the autonomous runtime loop off whatever the enable flags say. | The enable flags decide. |
| `OC_RUNNER_DISABLED` | No | unset | Set true, keeps the autonomous runtime loop off whatever the enable flags say. | The enable flags decide. |
| `CALYX_RUNTIME_DISABLED` | No | unset | Set true, keeps the autonomous runtime loop off whatever the enable flags say. | The enable flags decide. |
| `CALYX_RUNTIME_INTERVAL_SECONDS` | No | `30` (minimum 5) | Autonomous runtime loop interval; read before OC_RUNNER_INTERVAL_SECONDS. A non-integer uses 30. | OC_RUNNER_INTERVAL_SECONDS, then 30. |
| `OC_RUNNER_INTERVAL_SECONDS` | No | `30` (minimum 5) | Fallback for CALYX_RUNTIME_INTERVAL_SECONDS. | 30 seconds. |
| `OC_RUNNER_ACTIVE_MODE` | No | `true` | Runner worker mode: `true` is active, anything else reports `dry_run` (app/main.py). | Active mode. |
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

### Other variables read by `app/`

Every other name `app/` reads, found by a static scan
(`python scripts/list_env_reads.py`), with the reason it is outside the
checklist. The readiness checks do not report these.
`tests/test_release1_env_readiness.py` fails when `app/` reads a name that is
in neither table, or when this table and `app/release_env.py` drift apart.

| Why it is not in the Release 1 checklist | Variables |
|------------------------------------------|-----------|
| Paid model and provider integrations; NO_API_MODE keeps provider calls off for Release 1. | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `CALYX_AGENT_BASE_URL`, `CALYX_AGENT_MODEL`, `CALYX_AGENT_PROVIDER`, `CALYX_AGENT_TIMEOUT_SECONDS`, `CALYX_CHAT_API_KEY`, `CALYX_CHAT_COMPLETIONS_URL`, `CALYX_CHAT_MAX_TOKENS`, `CALYX_CHAT_MODEL`, `CALYX_CHAT_TIMEOUT_SECONDS`, `CALYX_VISION_ANTHROPIC_MODEL`, `CALYX_VISION_DURABLE_ENABLED`, `CALYX_VISION_EPHEMERAL_WRITES_ENABLED`, `CALYX_VISION_LIVE_INFERENCE_ENABLED`, `CALYX_VISION_PROVIDER` |
| Engineering, GitHub and orchestration automation lanes; not a Release 1 user journey. | `CALYX_ENGINEERING_ANTHROPIC_MODEL`, `CALYX_ENGINEERING_COMPLETION_POLL_SECONDS`, `CALYX_ENGINEERING_COMPLETION_WORKER_ID`, `CALYX_ENGINEERING_COMPLETION_WORKER_SECONDS`, `CALYX_ENGINEERING_ENABLED`, `CALYX_ENGINEERING_MODE`, `CALYX_ENGINEERING_PROVIDER_API_KEY`, `CALYX_ENGINEERING_PROVIDER_MODEL`, `CALYX_ENGINEERING_PROVIDER_TOKEN`, `CALYX_ENGINEERING_PROVIDER_URL`, `CALYX_ENGINEERING_REPOSITORY`, `CALYX_GITHUB_CODING_AGENT_TOKEN`, `CALYX_GITHUB_CODING_AUTONOMY_ENABLED`, `CALYX_GITHUB_CODING_AUTONOMY_OWNER`, `CALYX_GITHUB_CODING_AUTONOMY_POLL_SECONDS`, `CALYX_GITHUB_PROPOSAL_EXECUTOR_ENABLED`, `CALYX_GITHUB_PROPOSAL_EXECUTOR_OWNER`, `CALYX_GITHUB_PROPOSAL_REPOSITORIES`, `CALYX_GITHUB_RESEARCH_AUTHORS`, `CALYX_GITHUB_RESEARCH_BRIDGE_ENABLED`, `CALYX_GITHUB_RESEARCH_FEEDBACK_TOKEN`, `CALYX_GITHUB_RESEARCH_LABEL`, `CALYX_GITHUB_RESEARCH_MAX_PAYLOAD_BYTES`, `CALYX_GITHUB_RESEARCH_REPOSITORIES`, `CALYX_GITHUB_RESEARCH_WEBHOOK_SECRET`, `CALYX_ORCHESTRATOR_ENABLED`, `CALYX_ORCHESTRATOR_LEASE_SECONDS`, `CALYX_ORCHESTRATOR_MODE`, `CALYX_ORCHESTRATOR_POLL_SECONDS`, `CALYX_OWNER_REVOKED_KEY_IDS`, `CALYX_OWNER_VERIFY_KEYS_JSON`, `CALYX_PROGRAM_AUTONOMY_ENABLED`, `CALYX_PROGRAM_AUTONOMY_LEASE_SECONDS`, `CALYX_PROGRAM_AUTONOMY_MAX_JOBS_PER_CYCLE`, `CALYX_PROGRAM_AUTONOMY_OWNER`, `CALYX_PROGRAM_AUTONOMY_POLL_SECONDS`, `CALYX_PROGRAM_AUTONOMY_TIMEOUT_SECONDS`, `CALYX_PROGRAM_AUTONOMY_WORKER_ID`, `CALYX_SANDBOX_SUPERVISOR_TOKEN_SHA256`, `CALYX_WORKER_ID`, `CALYX_DRY_RUN_DIRECTORY`, `CALYX_ACTIVATION_STATE_PATH`, `GITHUB_REPOSITORY`, `GITHUB_TOKEN`, `GITHUB_WORKSPACE` |
| Archive, intake, Google Drive/Gmail and Zenodo pipelines; owner-operated ingestion, not a Release 1 user journey. | `ARCHIVE_ALLOWED_ROOTS`, `ARCHIVE_LEASE_SECONDS`, `ARCHIVE_LOCAL_WORKERS`, `ARCHIVE_MAX_FILE_BYTES`, `ARCHIVE_MAX_PATH_DEPTH`, `ARCHIVE_MAX_ZIP_EXPANSION_RATIO`, `ARCHIVE_MAX_ZIP_MEMBERS`, `ARCHIVE_MAX_ZIP_UNCOMPRESSED_BYTES`, `CALYX_SCIENTIFIC_ARCHIVE_STAGING`, `INTAKE_MAX_FILE_BYTES`, `INTAKE_STORAGE_DIR`, `GOOGLE_DRIVE_PILOT_FOLDER`, `GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON`, `GOOGLE_GMAIL_CREDENTIALS_JSON`, `GOOGLE_GMAIL_DELEGATED_USER`, `GOOGLE_GMAIL_SERVICE_ACCOUNT_JSON`, `CALYX_INTELLIGENCE_GMAIL_QUERY`, `ZENODO_ACCESS_TOKEN`, `ZENODO_API_BASE`, `ZENODO_COMMUNITY` |
| Taxonomy intake and activation; owner-gated, not activated in Release 1. | `CALYX_TAXONOMY_ACTIVE_BASELINE_PATH`, `CALYX_TAXONOMY_INTAKE_DIR`, `CALYX_TAXONOMY_INTAKE_PATH`, `CALYX_TAXONOMY_MAX_UPLOAD_BYTES` |
| Literature, external-source and scientific-pipeline settings; background pipelines, not assessed for this checklist. | `BHL_API_KEY`, `CROSSREF_MAILTO`, `CALYX_EXTERNAL_LITERATURE_ALWAYS`, `CALYX_EXTERNAL_LITERATURE_TIMEOUT_SECONDS`, `CALYX_CLIMATE_TIMEOUT_SECONDS`, `CALYX_DATA_INTELLIGENCE_ROOT`, `LITERATURE_EXTRACTION_ROOT`, `SCIENTIFIC_LANGUAGE_CANDIDATE_ROOT`, `SCIENTIFIC_LANGUAGE_FIGURE_REQUEST_ROOT`, `SCI_OBS_EXPORT_ENABLED` |
| Surfaces not assessed for this checklist (University, Conservatory storage, reference-document storage, reviewer qualifications, local Show Day rehearsal). | `OCU_UNIVERSITY_ENABLED`, `OCU_UNIVERSITY_LEARNER_AUTH_ENABLED`, `OCU_UNIVERSITY_RELEASE_EVIDENCE_ID`, `OCU_UNIVERSITY_SESSION_WRITES_ENABLED`, `CALYX_CONSERVATORY_DIR`, `CONSERVATORY_SCAN_BASE_URL`, `REFERENCE_DOCS_DIR`, `MISSION_CONTROL_REVIEWER_QUALIFICATIONS_JSON`, `CALYX_SHOW_CREATE_TABLES` |

### Other runtime settings

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PORT` | No | `3000` | Port to bind (set by the host in deployments); read by the start command, not by `app/` |
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
