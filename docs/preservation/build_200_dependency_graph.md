# BUILD 200 — Repository Dependency & Entry-Point Audit
# Orchid Continuum / Calyx Workspace

**Generated:** 2026-05-03
**Method:** Static file inspection only. No database connections, no SQL, no imports executed, no network calls.
**Files inspected:** 42 (39 Python, 2 shell scripts, 1 SQL seed file)

---

## 1. Complete File Inventory

### 1a. Calyx Application Package (`app/`)

| File | Role | DB Target | Entry Points |
|---|---|---|---|
| `app/main.py` | **CANONICAL FastAPI app** | PGHOST (heliumdb) via `app/database.py` | `app = FastAPI(...)`, `@app.on_event("startup")` |
| `app/database.py` | Engine factory (PGHOST → DATABASE_URL → SQLite) | PGHOST priority | `get_engine()`, `get_db()` |
| `app/models.py` | SQLAlchemy ORM models (32 Calyx tables) | heliumdb | — |
| `app/schemas.py` | Pydantic request/response schemas (660 lines) | — | — |
| `app/deps.py` | `get_db` passthrough shim | — | — |
| `app/security.py` | `X-API-Key`, `X-Judge-Id`, `X-Orchid-Admin-Key` auth | — | — |
| `app/storage.py` | SHA256 file storage, local disk only | — | — |
| `app/worker.py` | **Infinite loop job worker** | DATABASE_URL (via `app.database.get_engine()`) | `if __name__ == "__main__": main()` |
| `app/routers/awards.py` | Awards CRUD | heliumdb | — |
| `app/routers/calyx_core.py` | Orgs, contacts, events, templates, files, integrations | heliumdb | — |
| `app/routers/entries.py` | Entries CRUD | heliumdb | — |
| `app/routers/feedback.py` | Feedback capture | heliumdb | — |
| `app/routers/health.py` | `/health`, `/system/status` | — | — |
| `app/routers/judging.py` | Full judging system (937 lines) | heliumdb | — |
| `app/routers/reference_docs.py` | AOS PDF upload/download | heliumdb + local disk | — |
| `app/routers/shows.py` | Shows CRUD | heliumdb | — |
| `app/routers/tiles.py` | Navigation tile registry (static) | — | — |
| `app/routers/volunteer_ops.py` | Full volunteer ops, Excel import/export (600 lines) | heliumdb | — |
| `app/routers/volunteers.py` | Legacy volunteer tasks CRUD | heliumdb | — |
| `app/routers/__init__.py` | Empty init | — | — |

### 1b. Root-Level Scripts — GUARDED (Build 199)

| File | Guard at Line | Primary Risk | DB Target |
|---|---|---|---|
| `oc_extract_taxonomy.py` | 4 | **CRITICAL** — top-level UPDATE on import | DATABASE_URL (Neon) |
| `oc_extract_all.py` | 4 | **CRITICAL** — 30× subprocess launcher | via `oc_extract_taxonomy.py` |
| `oc_automation_worker.py` | 4 | **CRITICAL** — infinite loop, INSERTs | DATABASE_URL (Neon) |
| `mission_control_scheduler.py` | 4 | **CRITICAL** — infinite hourly loop, INSERTs | DATABASE_URL (Neon) |
| `oc_scheduler.py` | 4 | **CRITICAL** — infinite loop, UPDATEs + INSERTs | DATABASE_URL (Neon) |
| `oc_system_check_v2.py` | 4 | **HIGH** — stale table names, schema-stale | DATABASE_URL (Neon) |
| `orchid_api.py` | 7 | **MEDIUM** — standalone FastAPI, no auth | DATABASE_URL (Neon) |
| `oc_system_health.py` | 4 | **MEDIUM** — standalone FastAPI, no auth | DATABASE_URL (Neon) |

### 1c. Root-Level Scripts — UNGUARDED, Read-Only

| File | `__main__` Guard | Top-Level DB Connect | DB Target | Risk |
|---|---|---|---|---|
| `oc_control_panel.py` | NO | YES (called at module level) | DATABASE_URL (Neon) | LOW — read-only SELECT |
| `oc_ingestion_tracker.py` | NO | YES (line 7) | DATABASE_URL (Neon) | LOW — read-only COUNT |
| `oc_orchid_atlas.py` | NO | YES (line 10) | DATABASE_URL (Neon) | LOW — read-only SELECT, writes HTML |
| `oc_mission_control.py` | NO | YES (Streamlit `query()`) | DATABASE_URL (Neon) | LOW — read-only, requires `streamlit run` |
| `orchid_climate_engine.py` | NO | YES (line 16) + raises RuntimeError | DATABASE_URL (Neon) | **MEDIUM** — connects at top level, no guard |
| `python oc_system_check_v2.py` | YES (`__main__`) | Only when run directly | DATABASE_URL (Neon) | LOW — read-only schema discovery |

> **Note on `python oc_system_check_v2.py`:** This file is literally named with a leading `python ` prefix (0-character content aside — wait, 750+ lines). Its content is `oc_sentinel.py` — a sophisticated schema discovery tool using `CANDIDATE_GROUPS` to probe multiple table name variants. It correctly uses `if __name__ == "__main__"` to gate all logic. It is safe to import. When run directly it connects to Neon and generates `oc_sentinel_report.json` / `oc_sentinel_report.txt`. **This is the most capable system check in the repo** and should be the canonical diagnostic tool.

### 1d. Root-Level Scripts — UNGUARDED, Structural Concerns

| File | Issue | Risk |
|---|---|---|
| `api_occurrence_points.py` | `app = FastAPI()` + `import psycopg2` + `os.getenv("DATABASE_URL")` all at module level — no guard, no auth | **HIGH** — if `uvicorn api_occurrence_points:app` is run, exposes live Neon data with no authentication and `allow_origins=["*"]` CORS |
| `orchid_atlas.py` | Reads `orchid_points.csv` which does not exist in repo | **DEAD** — fails immediately on run with FileNotFoundError |
| `app → main.py` | Zero-byte ghost file (0 bytes, created 2026-01-29). Literal filename contains `→` character | **GHOST** — harmless but confusing; artefact of an aborted symlink or shell redirect |

### 1e. Migration Hook

| File | Targets | Risk |
|---|---|---|
| `alembic/env.py` | `DATABASE_URL` (Neon) — ignores `PGHOST` (heliumdb) | **CRITICAL** — imports `app.models.Base` (Calyx heliumdb schema) and applies it to Neon when any `alembic` CLI command is run. `alembic/versions/` is empty, so no migration SQL exists, but `alembic upgrade head` would still execute `create_all` style operations through the env.py target. See Section 7. |

### 1f. Developer Tools

| File | Role | DB Contact |
|---|---|---|
| `tools/introspect_api.py` | Lists Calyx API routes, exports `tools/openapi.json` | **Indirect** — imports `app.main`, which triggers `FastAPI()` instantiation and all router imports; does NOT call startup lifecycle but does import `app.database` |
| `tools/openapi.json` | Generated OpenAPI spec (stale artifact) | — |
| `oc_repo_inventory.sh` | Shell inventory, `git` + `find` only | None |
| `oc_full_system_audit.sh` | Shell + `psql` SELECTs against `DATABASE_URL` | Read-only Neon queries |
| `seed.sql` | Demo seed data for heliumdb Calyx tables | Calyx (heliumdb) |

### 1g. Planning Documents

| File | Status |
|---|---|
| `docs/oc_graph_architecture_canon_phase1.md` | Architecture specification for a planned graph overlay on Neon/Orchid Continuum. Not yet implemented. Read-only planning doc. |
| `docs/preservation/build_196A_current_state_preservation_index.md` | Preservation audit |
| `docs/preservation/build_197_root_level_script_triage.md` | Script triage |
| `docs/preservation/build_198_schema_alignment_audit.md` | Schema alignment audit |
| `docs/preservation/build_199_emergency_legacy_script_safety_lock.md` | Safety lock documentation |
| `docs/preservation/build_199A_safety_lock_verification.md` | Safety lock verification |

---

## 2. Dependency Graph

### 2a. Script-Calls-Script

```
oc_extract_all.py
  └── subprocess.run(["python", "oc_extract_taxonomy.py"])  × 30
        └── oc_extract_taxonomy.py  [independently guarded]

tools/introspect_api.py
  └── from app.main import app
        └── [imports all 11 routers]
        └── [imports app.database → triggers engine setup on first DB call]
```

### 2b. psycopg2 / psycopg Import Map

These files import `psycopg2` or `psycopg` directly (bypassing SQLAlchemy):

| File | Library | Guarded? |
|---|---|---|
| `oc_extract_taxonomy.py` | `psycopg2` | YES |
| `oc_extract_all.py` | none (via subprocess) | YES |
| `oc_automation_worker.py` | `psycopg` | YES |
| `mission_control_scheduler.py` | `psycopg2` | YES |
| `oc_scheduler.py` | `psycopg` | YES |
| `oc_system_check_v2.py` | `psycopg2` | YES |
| `orchid_api.py` | `psycopg2` | YES |
| `oc_system_health.py` | `psycopg2` | YES |
| `oc_control_panel.py` | `psycopg2` | NO — read-only |
| `oc_ingestion_tracker.py` | `psycopg2` | NO — read-only |
| `oc_orchid_atlas.py` | `psycopg2` | NO — read-only |
| `oc_mission_control.py` | `psycopg2` | NO — read-only, requires streamlit |
| `orchid_climate_engine.py` | `psycopg2` | **NO — top-level connect, no guard** |
| `api_occurrence_points.py` | `psycopg2` | **NO — inside route handler, app instantiated at top level** |
| `python oc_system_check_v2.py` | `psycopg2` | `__main__` guard only — no safety lock |

### 2c. `DATABASE_URL` Connection Map (Neon)

All root-level scripts that use `os.getenv("DATABASE_URL")` target Neon (Orchid Continuum). None target heliumdb (Calyx).

```
DATABASE_URL → Neon (Orchid Continuum)
  ├── oc_extract_taxonomy.py        GUARDED — UPDATE oc_occurrences
  ├── oc_automation_worker.py       GUARDED — INSERT oc_occurrences, oc_job_queue
  ├── mission_control_scheduler.py  GUARDED — INSERT oc_harvest_runs, pipeline_runs
  ├── oc_scheduler.py               GUARDED — UPDATE oc_harvest_targets, INSERT oc_job_queue
  ├── oc_system_check_v2.py         GUARDED — stale SELECT queries
  ├── orchid_api.py                 GUARDED — SELECT oc_occurrences
  ├── oc_system_health.py           GUARDED — SELECT oc_occurrences
  ├── oc_control_panel.py           UNGUARDED — read-only
  ├── oc_ingestion_tracker.py       UNGUARDED — read-only
  ├── oc_orchid_atlas.py            UNGUARDED — read-only
  ├── oc_mission_control.py         UNGUARDED — read-only
  ├── orchid_climate_engine.py      UNGUARDED — read-only SELECT (but raises on startup)
  ├── api_occurrence_points.py      UNGUARDED — read-only SELECT (high risk: no auth)
  ├── python oc_system_check_v2.py  __main__ guard only — read-only schema discovery
  └── alembic/env.py                MIGRATION HOOK — would apply Calyx DDL to Neon
```

### 2d. `PGHOST` / heliumdb Connection Map (Calyx)

All connections that reach heliumdb go through `app/database.py:get_engine()`:

```
PGHOST → heliumdb (Calyx)
  └── app/database.py get_engine()
        ├── app/main.py startup → Base.metadata.create_all() + _reconcile_schema()
        ├── app/routers/shows.py
        ├── app/routers/entries.py
        ├── app/routers/awards.py
        ├── app/routers/calyx_core.py
        ├── app/routers/judging.py
        ├── app/routers/volunteer_ops.py
        ├── app/routers/volunteers.py
        ├── app/routers/reference_docs.py
        ├── app/routers/feedback.py
        └── app/worker.py → harvest_jobs table [ORPHANED — table not in models]
```

### 2e. FastAPI Application Instances

| Instance | File | Auth | Registered Workflow | Guard |
|---|---|---|---|---|
| `FastAPI(title="Calyx...")` | `app/main.py` | X-API-Key (optional), X-Judge-Id, X-Orchid-Admin-Key | **YES** — "Calyx API" workflow | N/A (canonical) |
| `FastAPI()` | `orchid_api.py` | **None** | No | GUARDED |
| `FastAPI()` | `oc_system_health.py` | **None** | No | GUARDED |
| `FastAPI()` | `api_occurrence_points.py` | **None** | No | **UNGUARDED** |

### 2f. Infinite Loop Map

| Script | Loop Type | Trigger | Guard | Job Table |
|---|---|---|---|---|
| `oc_automation_worker.py` | `while True:` in `main()` | `if __name__ == "__main__"` | YES (Build 199) | `oc_job_queue` (Neon) |
| `oc_scheduler.py` | `while True:` in `main()` | `if __name__ == "__main__"` | YES (Build 199) | `oc_harvest_targets` + `oc_job_queue` (Neon) |
| `mission_control_scheduler.py` | `while True:` with `sleep(3600)` | `if __name__ == "__main__"` | YES (Build 199) | `oc_harvest_runs` + `pipeline_runs` (Neon) |
| `app/worker.py` | `while True:` in `main()` | `if __name__ == "__main__"` | **NO** | `harvest_jobs` (heliumdb? — table unknown) |

---

## 3. Duplicate Functionality Analysis

### 3a. Schedulers / Job Runners (3 systems — 3 different job tables)

| System | Status | Job Table | DB | Notes |
|---|---|---|---|---|
| `oc_scheduler.py` | GUARDED | `oc_harvest_targets`, `oc_job_queue` | Neon | Feeds jobs to automation worker |
| `mission_control_scheduler.py` | GUARDED | `oc_harvest_runs`, `pipeline_runs` | Neon | Hourly cadence, mission control loop |
| `app/worker.py` | **UNGUARDED** | `harvest_jobs` | heliumdb (inferred) | **ORPHANED** — `harvest_jobs` not in `app/models.py` or Neon schema |

These three systems are functionally related but operationally disconnected. They do not share a job table. The `oc_scheduler.py` + `oc_automation_worker.py` pair is the most coherent system (`oc_harvest_targets` → `oc_job_queue` → worker). `mission_control_scheduler.py` operates a parallel pipeline tracking system. `app/worker.py` targets a table that appears to not exist anywhere.

**Canonical system:** `oc_scheduler.py` + `oc_automation_worker.py` pair. `mission_control_scheduler.py` is a higher-level orchestrator. `app/worker.py` is orphaned.

### 3b. FastAPI APIs (4 instances)

| System | Status | Auth | Routes | Purpose |
|---|---|---|---|---|
| `app/main.py` | **CANONICAL** | Optional API key + judge header | ~60+ routes | Full Calyx show management |
| `orchid_api.py` | GUARDED | **None** | Unknown (168 lines) | Orchid Continuum data API |
| `oc_system_health.py` | GUARDED | **None** | 2 routes (`/`, `/db`) | Health + occurrence count |
| `api_occurrence_points.py` | **UNGUARDED** | **None** | 1 route (`/orchid_points`) | Occurrence lat/lon dump |

`oc_system_health.py`'s functionality is fully covered by `app/main.py`'s `/health` and `/system/status` endpoints. `api_occurrence_points.py` is a one-route stub that duplicates what `orchid_api.py` also provides.

**Canonical system:** `app/main.py` only.

### 3c. Atlas Visualization Systems (2)

| System | Status | Data Source | Output | Library |
|---|---|---|---|---|
| `orchid_atlas.py` | **DEAD** | `orchid_points.csv` (missing from repo) | `orchid_atlas.html` (pydeck 3D hexagon) | pydeck |
| `oc_orchid_atlas.py` | Unguarded, functional | Neon `oc_occurrences` (20,000 rows) | `orchid_atlas.html` (folium circles) | folium |

Both write to the same output filename `orchid_atlas.html`. `orchid_atlas.py` is dead — its data source does not exist. `oc_orchid_atlas.py` is functional but connects to Neon at the top level without a guard.

**Canonical system:** `oc_orchid_atlas.py` (if atlas output is needed). `orchid_atlas.py` should be retired.

### 3d. System Check / Health Diagnostics (2+)

| System | Status | Table Discovery | Output | Guard |
|---|---|---|---|---|
| `oc_system_check_v2.py` | GUARDED | Hardcoded stale names (all 7 wrong) | Print to stdout | Build 199 |
| `python oc_system_check_v2.py` (oc_sentinel.py) | `__main__` guard only | **Adaptive** — tries candidate groups per table | `oc_sentinel_report.json` + `.txt` | `__main__` guard |
| `oc_control_panel.py` | Unguarded read-only | Hardcoded table names | Print to stdout | None |
| `oc_mission_control.py` | Streamlit | Hardcoded + try/except | Streamlit dashboard | None (requires streamlit run) |

**Canonical system:** `python oc_system_check_v2.py` (oc_sentinel.py) — the only system that adapts to schema drift via `CANDIDATE_GROUPS`. Should be renamed to `oc_sentinel.py` to eliminate the misleading filename.

### 3e. Occurrence Data APIs (2 overlapping stubs)

| System | Route | Auth | Guard |
|---|---|---|---|
| `api_occurrence_points.py` | `GET /orchid_points` → `{lat, lon}` | None | **UNGUARDED** |
| `orchid_api.py` | Unknown — needs review | None | GUARDED |

Both expose Neon occurrence data without authentication.

---

## 4. Dead and Orphaned Systems

### Dead (non-functional as-is)

| File | Reason | Safe to Remove? |
|---|---|---|
| `orchid_atlas.py` | Reads `orchid_points.csv` which does not exist | Yes — `oc_orchid_atlas.py` is the live equivalent |
| `app → main.py` | Zero-byte ghost file (0 bytes). Filename contains `→` character. Likely artifact of a shell redirect or aborted `ln -s`. | Yes — completely empty |
| `tools/openapi.json` | Stale generated artifact from a prior `tools/introspect_api.py` run | Yes — regenerated on each run |

### Orphaned (functional code, disconnected from current system)

| File | Reason | Safe to Remove? |
|---|---|---|
| `app/worker.py` | Targets `harvest_jobs` table. This table is not defined in `app/models.py` and was not found in Neon or heliumdb inventory. The worker loop would start, query for jobs, find nothing, and sleep in a 2-second loop forever without effect. No Replit workflow is registered for it. | Needs confirmation — if `harvest_jobs` was intentionally planned, retire with note |
| `oc_system_check_v2.py` | All 7 table queries use stale names that don't exist. Guarded. If unguarded and run, would print zero results for every check — false all-clear. Superseded by `oc_sentinel.py`. | Yes — but only after `oc_sentinel.py` is confirmed as replacement |

---

## 5. Critical Unguarded Risks (Not in Build 199)

These files were excluded from Build 199 guards (as read-only or low-risk) but have structural concerns that may warrant attention:

### Risk 1: `api_occurrence_points.py` — HIGHEST UNGUARDED RISK

```python
from fastapi import FastAPI    # line 1
import psycopg2                # line 2
import os                      # line 3

app = FastAPI()                # line 5 — executes at module load
DB = os.getenv("DATABASE_URL") # line 7

@app.get("/orchid_points")
def orchid_points():
    conn = psycopg2.connect(DB)  # connects when route is hit
    ...
```

If `uvicorn api_occurrence_points:app` is run (accidentally or deliberately), this exposes all `oc_occurrences` lat/lon coordinates from Neon with no authentication and no rate limiting. CORS is FastAPI's default (no restriction). This is worse than `orchid_api.py` and `oc_system_health.py` because it has no guard at all.

**Recommended action:** Add Build 199-style guard, OR retire (functionality is duplicated by guarded `orchid_api.py`).

### Risk 2: `orchid_climate_engine.py` — Top-Level Connect + RuntimeError

```python
DATABASE_URL = os.getenv("DATABASE_URL")   # line 11

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable not set")  # line 14

conn = psycopg2.connect(DATABASE_URL)      # line 16 — EXECUTES ON IMPORT
```

No `__main__` guard. No safety lock. Connecting to Neon and reading 50,000 rows happens on any invocation. Not write-capable (SELECT only, writes CSV), but the top-level `raise RuntimeError` is unusual — it would crash any process that imports this file in a context where `DATABASE_URL` is not set.

**Recommended action:** Add `if __name__ == "__main__"` guard at minimum, or add Build 199-style safety lock.

### Risk 3: `alembic/env.py` — Wrong Database Target

```python
from app.models import Base       # Calyx heliumdb models
target_metadata = Base.metadata   # 32 Calyx tables

def get_url():
    return os.getenv("DATABASE_URL", "sqlite:///./calyx.db")  # → Neon if DATABASE_URL set
```

Running any `alembic` CLI command (`alembic current`, `alembic check`, `alembic upgrade head`) executes `env.py`. With `DATABASE_URL` pointing to Neon:
- `alembic current` would connect to Neon and check migration state against the Calyx schema — harmless but misleading
- `alembic upgrade head` would attempt to apply Calyx DDL to Neon — potentially destructive

The `alembic/versions/` directory is **empty** — no migration files exist — which limits the blast radius. But the fundamental target mismatch means the Alembic setup is non-functional and misleading for either database.

**Recommended action:** Either update `get_url()` to use `get_database_url()` from `app/database.py` (to correctly target heliumdb), or add a comment warning that Alembic is scaffolded but not actively used, and that running migrations is blocked pending correct target configuration.

---

## 6. Entry Point Summary

### Scripts with `if __name__ == "__main__"` guard

| File | Loop Inside | DB Contact |
|---|---|---|
| `oc_automation_worker.py` | YES (infinite) | Neon |
| `oc_scheduler.py` | YES (infinite) | Neon |
| `mission_control_scheduler.py` | YES (infinite, hourly) | Neon |
| `app/worker.py` | YES (infinite) | heliumdb (harvest_jobs, orphaned) |
| `tools/introspect_api.py` | No | Indirect (imports app.main) |
| `python oc_system_check_v2.py` | No | Neon (read-only) |

### Scripts with NO `__main__` guard (all top-level code executes on any invocation)

| File | What Executes at Top Level |
|---|---|
| `oc_extract_taxonomy.py` | DB connect + SELECT + UPDATE loop + commit → **GUARDED** |
| `oc_control_panel.py` | Banner prints + multiple `run(sql)` calls (each opens connection) → UNGUARDED |
| `oc_ingestion_tracker.py` | `psycopg2.connect(DB)` at line 7, SELECT COUNT → UNGUARDED |
| `oc_orchid_atlas.py` | `psycopg2.connect(DB)` at line 10, SELECT 20,000 rows → UNGUARDED |
| `oc_mission_control.py` | `st.set_page_config(...)` at line 6, requires streamlit runtime → LOW RISK |
| `orchid_climate_engine.py` | `psycopg2.connect(DATABASE_URL)` at line 16 + `raise RuntimeError` → UNGUARDED |
| `orchid_atlas.py` | `pd.read_csv("orchid_points.csv")` at line 4 → DEAD (file missing) |
| `api_occurrence_points.py` | `app = FastAPI()` at line 5, `DB = os.getenv(...)` at line 7 → UNGUARDED |

---

## 7. The Alembic Problem (Detailed)

The Alembic setup in this repo is non-functional in both directions:

| Direction | Problem |
|---|---|
| `alembic upgrade head` against heliumdb | Would fail — `get_url()` returns `DATABASE_URL` (Neon) when set, not heliumdb. It only falls through to SQLite if `DATABASE_URL` is unset. |
| `alembic upgrade head` against Neon | Would attempt to apply Calyx's 32-table ORM schema to a 302-table Neon database. `alembic/versions/` is empty so no migration SQL runs — but the target mismatch means the setup is misleading. |
| `alembic check` | Connects to Neon, compares Calyx Base.metadata against Neon — meaningless result |

**Recommended fix (minimal):** Change `get_url()` in `alembic/env.py` to:
```python
def get_url():
    from app.database import get_database_url
    return get_database_url()  # PGHOST → DATABASE_URL → SQLite (correct heliumdb priority)
```
This makes Alembic target heliumdb instead of Neon when `PGHOST` is set.

---

## 8. Recommended Retirement Candidates

Listed from highest confidence to lowest.

| File | Recommendation | Reason |
|---|---|---|
| `app → main.py` | **RETIRE immediately** | Zero-byte ghost file. Harmless but confusing. |
| `orchid_atlas.py` | **RETIRE** | Dead — reads CSV that doesn't exist. Superseded by `oc_orchid_atlas.py`. |
| `tools/openapi.json` | **RETIRE** | Stale generated artifact. Add to `.gitignore`. |
| `oc_system_check_v2.py` | **RETIRE after oc_sentinel confirmed** | All table names stale. Guarded so inert. `oc_sentinel.py` is the capable replacement. |
| `api_occurrence_points.py` | **RETIRE or guard** | One-endpoint unauth'd stub. Duplicated by guarded `orchid_api.py`. Highest unguarded risk in repo. |
| `app/worker.py` | **RETIRE or document intent** | Targets `harvest_jobs` table that doesn't exist. Silent infinite loop that does nothing. If the table was planned, document it. |
| `app/routers/volunteers.py` | **Consider retiring** | Legacy volunteer tasks router, superseded by full `volunteer_ops.py`. Both are included in `app/main.py`. The `VolunteerTask` model may conflict with the expanded volunteer system. |

---

## 9. Recommended Canonical Systems

| Domain | Canonical System | Notes |
|---|---|---|
| **Calyx show management API** | `app/main.py` (uvicorn, "Calyx API" workflow) | Only registered entry point |
| **Calyx DB engine** | `app/database.py:get_engine()` | PGHOST-priority, correct |
| **OC data diagnostic** | `python oc_system_check_v2.py` (oc_sentinel.py) | Adaptive table discovery, `__main__` guard, JSON reports |
| **OC job scheduler** | `oc_scheduler.py` + `oc_automation_worker.py` | Coherent pair sharing `oc_job_queue` |
| **OC mission orchestration** | `mission_control_scheduler.py` | Higher-level, hourly cadence |
| **OC atlas visualization** | `oc_orchid_atlas.py` | Live Neon data, folium output |
| **OC metrics dashboard** | `oc_mission_control.py` | Streamlit, read-only |
| **OC metrics CLI** | `oc_control_panel.py` | Print-to-stdout, read-only |

---

## 10. Recommended Future Architecture

Based on the evidence in this repo, the workspace contains two distinct systems that have grown entangled:

### System A: Calyx (orchid show management)
- **DB:** heliumdb (PGHOST)
- **Entry point:** `app/main.py` via uvicorn
- **Models:** `app/models.py` (32 tables)
- **Status:** Production-ready, active, guarded

### System B: Orchid Continuum (GBIF occurrence data pipeline)
- **DB:** Neon (DATABASE_URL), 15 named schemas, 302+ tables
- **Entry points:** 6+ root-level scripts, 3 schedulers
- **Status:** Partially operational, schema-stale in places, needs Build 199B column audit

**Recommended separation:**

1. **Guard `api_occurrence_points.py`** (or retire it) — this is the one remaining unguarded FastAPI in the non-Streamlit tier.

2. **Guard or add `__main__` to `orchid_climate_engine.py`** — top-level DB connect without guard is the pattern that caused the `oc_extract_taxonomy.py` problem.

3. **Fix `alembic/env.py`** to use `get_database_url()` from `app/database.py` — or add a clear comment that Alembic is scaffolded but non-functional until this is resolved.

4. **Rename `python oc_system_check_v2.py`** to `oc_sentinel.py` — it is the most capable diagnostic tool in the repo but its filename defeats discoverability. The `oc_system_check_v2.py` (guarded, stale) should be retired once `oc_sentinel.py` is promoted.

5. **Document or provision `harvest_jobs` table** for `app/worker.py` — either add it to `app/models.py` with a proper schema and a registered Replit workflow, or retire the file if it was a prototype.

6. **Build 199B (Julius):** Column-level schema verification for `oc_occurrences`, `oc_harvest_targets`, `oc_harvest_runs`, `oc_job_queue`. This is the prerequisite for unlocking any of the 5 guarded write-capable scripts.

---

## Appendix: File Count by Category

| Category | Count |
|---|---|
| Calyx app package (`app/`) | 20 files |
| Root scripts — Build 199 guarded | 8 files |
| Root scripts — unguarded read-only | 5 files |
| Root scripts — unguarded structural concern | 3 files (`api_occurrence_points.py`, `orchid_climate_engine.py`, `orchid_atlas.py`) |
| Ghost / zero-byte | 1 file (`app → main.py`) |
| Migration hook | 1 file (`alembic/env.py`) |
| Developer tools | 2 files (`tools/introspect_api.py`, `tools/openapi.json`) |
| Shell scripts | 2 files |
| SQL | 1 file (`seed.sql`) |
| Planning docs | 7 documents (`docs/`) |
| **Total project files** | **~42** |
