# BUILD 197 — Root-Level Script Triage
# Orchid Continuum / Calyx Workspace

**Generated:** 2026-05-03
**Method:** Static inspection only. No scripts run. No SQL executed. No database touched.
**Files inspected at root level:** 36

---

## Classification Key

| Label | Meaning |
|---|---|
| `ACTIVE_PRODUCTION` | Currently serving requests or required for the live API |
| `ACTIVE_SUPPORT` | Not in the request path but actively useful (seed data, tools, config) |
| `LEGACY` | Was useful at a past stage; now superseded but not harmful if read |
| `PROTOTYPE` | Experimental script from an earlier build phase; not production-ready |
| `BROKEN_OR_ORPHANED` | Cannot be used as-is due to filename, empty content, or structural error |
| `WRITE_CAPABLE_HIGH_RISK` | Can write, update, or delete from a live database if run |
| `UNKNOWN_NEEDS_REVIEW` | Purpose unclear without deeper context; do not run without review |

---

## Full Triage Table

### Python Files

---

#### `oc_automation_worker.py`
- **Classification:** `WRITE_CAPABLE_HIGH_RISK`
- **Purpose:** Infinite worker loop that claims jobs from `oc_job_queue`, calls GBIF API, and bulk INSERTs occurrences into `oc_occurrences`.
- **DB libraries:** `psycopg`, `requests`
- **Env vars:** `DATABASE_URL`
- **Write operations:** `INSERT INTO oc_occurrences`, `UPDATE oc_job_queue SET status='running'/'completed'`, `FOR UPDATE SKIP LOCKED`
- **Runnable:** Yes — will run immediately as an infinite loop
- **Risk:** CRITICAL
- **Schema note:** References `oc_job_queue` and `oc_occurrences` — these table names exist in Neon (confirmed in `orchid_continuum_db_audit_current.txt`) but the schema may have drifted. `oc_occurrences` had 114,517 rows as of 2026-03-14.
- **Recommendation:** Never run without review. Belongs in Orchid Continuum repo, not Calyx.

---

#### `oc_scheduler.py`
- **Classification:** `WRITE_CAPABLE_HIGH_RISK`
- **Purpose:** Infinite loop that picks harvest targets from `oc_harvest_targets` and enqueues jobs into `oc_job_queue`.
- **DB libraries:** `psycopg`
- **Env vars:** `DATABASE_URL`
- **Write operations:** `INSERT INTO oc_job_queue`, `UPDATE oc_harvest_targets SET state='processing'`, `FOR UPDATE SKIP LOCKED`
- **Runnable:** Yes — will run immediately as an infinite loop
- **Risk:** CRITICAL
- **Schema note:** `oc_harvest_targets` and `oc_job_queue` confirmed present in Neon (audit 2026-03-14).
- **Recommendation:** Never run without review. Belongs in Orchid Continuum repo.

---

#### `mission_control_scheduler.py`
- **Classification:** `WRITE_CAPABLE_HIGH_RISK`
- **Purpose:** Hourly orchestration loop — launches GBIF harvest runs, triggers taxonomy/trait/image pipelines, checks worker registry.
- **DB libraries:** `psycopg2`
- **Env vars:** `DATABASE_URL`
- **Write operations:** `INSERT INTO oc_harvest_runs`, `INSERT INTO pipeline_runs`, reads `oc_worker_registry`
- **Runnable:** Yes — infinite loop, sleeps 3600s between iterations
- **Risk:** CRITICAL
- **Schema note:** `oc_harvest_runs` confirmed in Neon audit. `pipeline_runs` also confirmed (Neon audit line 85).
- **Recommendation:** Never run without review. If triggered accidentally, would INSERT into Neon every hour until killed.

---

#### `oc_extract_all.py`
- **Classification:** `WRITE_CAPABLE_HIGH_RISK`
- **Purpose:** Runs `oc_extract_taxonomy.py` 30 times via `subprocess.run`. Acts as a batch multiplier.
- **DB libraries:** `subprocess` only (inherits DB from child)
- **Env vars:** Inherited by child process
- **Write operations:** 30 × whatever `oc_extract_taxonomy.py` does (5,000 UPDATEs per batch = up to 150,000 row updates)
- **Runnable:** Yes — runs immediately, spawns 30 sequential subprocesses
- **Risk:** CRITICAL
- **Recommendation:** Never run without review. No dry-run mode. No confirmation prompt.

---

#### `oc_extract_taxonomy.py`
- **Classification:** `WRITE_CAPABLE_HIGH_RISK`
- **Purpose:** Reads 5,000 `oc_occurrences` rows with `species_id IS NULL`, parses GBIF JSON, and batch-UPDATEs `species_id`, `genus_id`, `country`, `elevation_m`.
- **DB libraries:** `psycopg2`
- **Env vars:** `DATABASE_URL`
- **Write operations:** `UPDATE oc_occurrences SET species_id, genus_id, country, elevation_m WHERE occurrence_id = ...` (up to 5,000 rows per run)
- **Runnable:** Yes — runs to completion and exits
- **Risk:** HIGH
- **Schema note:** Reads from `raw_json` column (GBIF occurrence data). Writes to 4 columns. No rollback guard.
- **Recommendation:** Never run without review. Especially dangerous when chained via `oc_extract_all.py`.

---

#### `app/worker.py`
- **Classification:** `ACTIVE_SUPPORT` (write-capable, lower risk)
- **Purpose:** Harvest job worker for the Calyx/heliumdb side. Polls `harvest_jobs`, marks jobs running/done. Currently a placeholder (actual harvester logic is `time.sleep(1)`).
- **DB libraries:** SQLAlchemy via `app.database.get_engine()`
- **Env vars:** Inherits from app (PGHOST)
- **Write operations:** `UPDATE harvest_jobs SET status='running'`, `UPDATE harvest_jobs SET status='done'`, `FOR UPDATE SKIP LOCKED`
- **Runnable:** Yes — infinite loop
- **Risk:** MEDIUM (targets heliumdb, not Neon; logic is a no-op placeholder)
- **Recommendation:** Keep. Document that actual harvester logic has not been implemented. Do not run in production until a real job handler is added.

---

#### `oc_mission_control.py`
- **Classification:** `PROTOTYPE`
- **Purpose:** Streamlit dashboard showing occurrence count, harvest targets, job queue, harvest status, occurrence sample.
- **DB libraries:** `psycopg2`, `pandas`
- **Env vars:** `DATABASE_URL`
- **Write operations:** None — SELECT only
- **Runnable:** Yes, with `streamlit run oc_mission_control.py` (Streamlit not in requirements.txt)
- **Risk:** LOW (read-only)
- **Schema note:** Queries `oc_occurrences`, `oc_harvest_targets`, `oc_job_queue` — all exist in Neon.
- **Recommendation:** Document as legacy prototype dashboard. Safe to read. Not connected to any workflow.

---

#### `oc_control_panel.py`
- **Classification:** `PROTOTYPE`
- **Purpose:** CLI metrics panel — prints occurrence count, species count, genus count, country count, elevation stats.
- **DB libraries:** `psycopg2`, `pandas`
- **Env vars:** `DATABASE_URL`
- **Write operations:** None — SELECT only
- **Runnable:** Yes — connects to DATABASE_URL on import/run and runs immediately
- **Risk:** LOW (read-only; will error if `oc_occurrences` schema differs)
- **Recommendation:** Safe to read. Runs on import — do not import in another module.

---

#### `oc_ingestion_tracker.py`
- **Classification:** `PROTOTYPE`
- **Purpose:** Single-query script that counts `oc_occurrences` and prints to stdout.
- **DB libraries:** `psycopg2`, `pandas`
- **Env vars:** `DATABASE_URL`
- **Write operations:** None — one SELECT COUNT
- **Runnable:** Yes — executes and connects on import (top-level code, not in `__main__`)
- **Risk:** LOW
- **Recommendation:** Safe to read. Note: DB connection opens at module import, not guarded by `if __name__ == '__main__'`.

---

#### `oc_system_health.py`
- **Classification:** `PROTOTYPE`
- **Purpose:** Standalone FastAPI app with `/` and `/db` endpoints. Counts `oc_occurrences`.
- **DB libraries:** `psycopg2`, `fastapi`
- **Env vars:** `DATABASE_URL`
- **Write operations:** None — SELECT only
- **Runnable:** Yes, with `uvicorn oc_system_health:app` — not in any workflow
- **Risk:** LOW (read-only, but unregistered app would expose unauth'd endpoint if started)
- **Recommendation:** Document as legacy prototype. Do not add to `.replit` workflow without adding auth.

---

#### `oc_system_check_v2.py`
- **Classification:** `LEGACY`
- **Purpose:** Comprehensive diagnostic script — checks occurrence records, images, taxonomy, atlas grid, elevation, traits, harvesters, media integrity.
- **DB libraries:** `psycopg2`
- **Env vars:** `DATABASE_URL`
- **Write operations:** None — SELECT/COUNT only (includes `conn.rollback()` on error)
- **Runnable:** Yes — runs queries and prints results
- **Risk:** LOW (read-only; references old table names: `oc_occurrence_records`, `oc_taxa`, `oc_images`, `oc_harvesters`, `oc_harvester_runs`, `oc_atlas_cells`, `oc_traits` — most do NOT exist in current Neon schema)
- **Schema gap:** Current Neon uses `orchid_images`, `harvesters`, `judging_criteria` — not `oc_images` or `oc_harvesters`. Queries will fail gracefully (rollback on each error).
- **Recommendation:** Keep as historical reference. Do not use as current health check — schema has changed.

---

#### `orchid_api.py`
- **Classification:** `PROTOTYPE`
- **Purpose:** Full standalone FastAPI app for Orchid Continuum — occurrence points, taxa counts, elevation stats, climate/images/vision placeholders.
- **DB libraries:** `psycopg2`, `fastapi`
- **Env vars:** `DATABASE_URL` (raises RuntimeError if missing)
- **Write operations:** None — SELECT only + placeholder returns
- **Runnable:** Yes, with `uvicorn orchid_api:app` — not in any workflow
- **Risk:** LOW-MEDIUM (read-only, but exposes unauth'd API if started; references `oc_occurrences` which exists in Neon)
- **Recommendation:** Document as early OC API prototype. Superseded by Calyx. Do not activate without auth.

---

#### `oc_orchid_atlas.py`
- **Classification:** `PROTOTYPE`
- **Purpose:** Reads up to 20,000 lat/lon from `oc_occurrences`, generates a Folium HTML map, saves as `orchid_atlas.html`.
- **DB libraries:** `psycopg2`, `pandas`, `folium`
- **Env vars:** `DATABASE_URL` (connects on import — top-level code)
- **Write operations:** None to DB — writes `orchid_atlas.html` to local filesystem
- **Runnable:** Yes (requires `folium` which is not in requirements.txt)
- **Risk:** LOW (read-only DB; local file write only)
- **Recommendation:** Keep as reference. Output file `orchid_atlas.html` already present.

---

#### `orchid_climate_engine.py`
- **Classification:** `PROTOTYPE`
- **Purpose:** Reads occurrence lat/lon from `oc_occurrences`, computes approximate climate envelopes per genus (no external API — math-only), writes `orchid_climate_profiles.csv`.
- **DB libraries:** `psycopg2`, `pandas`, `numpy`
- **Env vars:** `DATABASE_URL` (raises RuntimeError if missing)
- **Write operations:** None to DB — writes `orchid_climate_profiles.csv` locally
- **Runnable:** Yes — runs end-to-end in one pass
- **Risk:** LOW (read-only DB; local file write only)
- **Recommendation:** Keep as reference. Note: climate estimates are mathematical approximations from latitude only, not real WorldClim data.

---

#### `api_occurrence_points.py`
- **Classification:** `PROTOTYPE`
- **Purpose:** Minimal FastAPI app with single endpoint `/orchid_points` returning lat/lon from `oc_occurrences`.
- **DB libraries:** `psycopg2`, `fastapi`
- **Env vars:** `DATABASE_URL`
- **Write operations:** None — SELECT only
- **Runnable:** Yes, with `uvicorn api_occurrence_points:app`
- **Risk:** LOW (read-only; unregistered)
- **Recommendation:** Superseded. Document as prototype. Do not activate.

---

#### `alth.py,` *(filename includes trailing comma)*
- **Classification:** `BROKEN_OR_ORPHANED`
- **Purpose:** Duplicate health router — defines `GET /health` and `GET /system/status` using FastAPI `APIRouter`.
- **DB libraries:** None
- **Env vars:** None
- **Write operations:** None
- **Runnable:** No — filename contains a comma; cannot be imported with `import alth` or run normally
- **File size:** 295 bytes
- **Risk:** LOW (harmless, just confusing)
- **Recommendation:** Document as orphaned. Do not rename or delete without explicit approval.

---

#### `app → main.py` *(zero-byte file, not a symlink)*
- **Classification:** `BROKEN_OR_ORPHANED`
- **Purpose:** Unknown — name suggests a failed attempt to create a symlink pointing `app` to `main.py`, or an artifact from a file creation command that went wrong.
- **DB libraries:** None (0 bytes)
- **Env vars:** None
- **Write operations:** None
- **Runnable:** No
- **File size:** 0 bytes
- **Risk:** LOW (harmless; causes confusion about repo structure)
- **Recommendation:** Document as broken. Do not delete without explicit approval.

---

#### `python oc_system_check_v2.py` *(filename starts with "python ")*
- **Classification:** `BROKEN_OR_ORPHANED`
- **Purpose:** Appears to be a copy of `oc_system_check_v2.py` — same diagnostic content (28,214 bytes match).
- **DB libraries:** `psycopg2`
- **Env vars:** `DATABASE_URL`
- **Write operations:** None — SELECT only (with rollback guards)
- **Runnable:** No by normal means — the space in the filename means it cannot be imported with `import python oc_system_check_v2` and shell execution would be confused by the prefix
- **File size:** 28,214 bytes
- **Risk:** LOW (cannot be run normally)
- **Recommendation:** Document as orphaned duplicate. Likely created by a shell command that accidentally prepended `python` to the output filename.

---

### Shell Scripts

---

#### `oc_repo_inventory.sh`
- **Classification:** `ACTIVE_SUPPORT`
- **Purpose:** Generates a timestamped repo inventory snapshot (git metadata, top-level listing, entrypoints, stack signals). Writes output to `OC_REPO_INVENTORY_<timestamp>.txt`.
- **DB libraries:** None (pure shell)
- **Env vars:** None
- **Write operations:** None to DB — writes a `.txt` file to local filesystem
- **Runnable:** Yes — safe to run anytime
- **Risk:** LOW
- **Recommendation:** Keep. Useful for orientation. Will produce a new snapshot file on each run.

---

#### `oc_full_system_audit.sh`
- **Classification:** `ACTIVE_SUPPORT`
- **Purpose:** Runs a series of read-only `psql` COUNT queries against DATABASE_URL — checks table sizes for images, harvesters, GBIF queues, elevation, automation, image quality.
- **DB libraries:** `psql` (requires PostgreSQL client)
- **Env vars:** `DATABASE_URL`
- **Write operations:** None — SELECT COUNT queries only
- **Runnable:** Yes — requires `psql` and `DATABASE_URL` set
- **Risk:** LOW (read-only)
- **Recommendation:** Keep. Useful operational health check. Safe to run.

---

### SQL Files

---

#### `seed.sql`
- **Classification:** `ACTIVE_SUPPORT`
- **Purpose:** Demo seed data for Calyx — 1 org, 1 show, 5 entries, 3 volunteer roles, 5 shifts, 6 volunteers, 6 assignments, 3 judges, 10 legacy score submissions, 3 awards.
- **DB libraries:** N/A (raw SQL)
- **Env vars:** N/A (run via psql against target)
- **Write operations:** `INSERT INTO` (organizations, shows, entries, volunteer_roles, volunteer_shifts, volunteers, volunteer_assignments, judges, score_submissions, awards) — all with `ON CONFLICT (id) DO NOTHING`
- **Runnable:** Yes, idempotent — safe for heliumdb (Calyx dev)
- **Risk:** LOW (idempotent, uses demo UUIDs like 'show-001')
- **Recommendation:** Keep. Intended for heliumdb only. Do not run against Neon.

---

#### `orchid_schema.sql`
- **Classification:** `BROKEN_OR_ORPHANED`
- **Purpose:** Intended as a schema export — filename suggests it should contain DDL. Currently empty.
- **DB libraries:** N/A
- **Env vars:** N/A
- **Write operations:** N/A (empty)
- **Runnable:** No (empty)
- **File size:** 0 bytes
- **Risk:** LOW (harmless placeholder)
- **Recommendation:** Document as empty. Do not treat as a real schema backup.

---

#### `migrations/001_create_system_reference_documents.sql`
- **Classification:** `ACTIVE_SUPPORT`
- **Purpose:** DDL migration to create `system_reference_documents` table, two regular indexes, and one unique index.
- **DB libraries:** N/A (raw SQL)
- **Env vars:** N/A
- **Write operations:** `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS` (all idempotent)
- **Runnable:** Yes — idempotent DDL
- **Risk:** LOW
- **Recommendation:** Keep. Part of Calyx schema management history.

---

### Configuration Files

---

#### `.replit`
- **Classification:** `ACTIVE_PRODUCTION`
- **Purpose:** Replit workflow and deployment configuration. Defines the `Calyx API` workflow (uvicorn on port 3000), deployment target (autoscale), and port mappings.
- **DB libraries:** N/A
- **Env vars:** Reads `${PORT:-3000}` in deployment run command
- **Write operations:** N/A
- **Runnable:** N/A (config file)
- **Risk:** LOW
- **Notable:** Port 8501 mapped (Streamlit default) but Streamlit is not in `requirements.txt` and no workflow uses it.
- **Recommendation:** Keep. Do not modify without understanding workflow impact.

---

#### `alembic.ini`
- **Classification:** `ACTIVE_SUPPORT` (inactive but present)
- **Purpose:** Alembic configuration file — sets script location to `./alembic`.
- **DB libraries:** N/A (config)
- **Env vars:** Indirectly (Alembic reads DATABASE_URL via `alembic/env.py`)
- **Write operations:** N/A (config only)
- **Runnable:** Used by `alembic` CLI, not directly
- **Risk:** MEDIUM — if anyone runs `alembic upgrade head`, `alembic/env.py` would target `DATABASE_URL` (Neon!) by default. With no migration files in `alembic/versions/`, this would likely no-op, but the configuration is misleading.
- **Recommendation:** Document the risk. Add a comment in `alembic.ini` noting that migrations are not used — schema is managed via `_safe_add_column()` in `app/main.py`.

---

#### `alembic/env.py`
- **Classification:** `ACTIVE_SUPPORT` (scaffolded, inactive)
- **Purpose:** Alembic environment setup — configures SQLAlchemy connection and migration context.
- **DB libraries:** `sqlalchemy`, `alembic`
- **Env vars:** `DATABASE_URL` (defaults to `sqlite:///./calyx.db` if not set)
- **Write operations:** Would execute `CREATE TABLE`, `ALTER TABLE` etc. if `alembic upgrade` is run and migrations exist
- **Runnable:** Only via `alembic` CLI
- **Risk:** HIGH — **points to `DATABASE_URL` (Neon production) by default**. If a migration file were ever added to `alembic/versions/` and `alembic upgrade head` were run, it would run DDL against Neon.
- **Recommendation:** Document this risk prominently. Consider adding an explicit guard that checks if DATABASE_URL points to Neon and aborts.

---

#### `requirements.txt`
- **Classification:** `ACTIVE_PRODUCTION`
- **Purpose:** Python dependency list for the Calyx API.
- **DB libraries:** `sqlalchemy`, `psycopg2-binary`, `alembic`
- **Env vars:** N/A
- **Write operations:** N/A
- **Runnable:** N/A (pip install target)
- **Risk:** LOW
- **Notable:** Contains duplicates (`fastapi`, `pydantic`, `python-multipart`, `sqlalchemy`, `uvicorn` each listed twice). Does not include `pandas`, `psycopg`, `folium`, `streamlit`, `numpy` — required by several root-level OC scripts.
- **Recommendation:** Keep. Remove duplicates in a future cleanup build.

---

#### `README.md`
- **Classification:** `ACTIVE_SUPPORT` (outdated)
- **Purpose:** Public-facing API documentation.
- **DB libraries:** N/A
- **Env vars:** Documents `DATABASE_URL`, `PORT`, `CORS_ALLOW_ORIGINS`, `CALYX_API_KEY`, `AUTO_CREATE_TABLES`
- **Write operations:** N/A
- **Runnable:** N/A
- **Risk:** LOW
- **Notable:** Does not document the judging system, scorecard workflow, volunteer ops, or AOS criteria endpoints — all added after README was last updated.
- **Recommendation:** Update in Build 201.

---

#### `replit.md`
- **Classification:** `ACTIVE_PRODUCTION`
- **Purpose:** Authoritative architecture memory for Replit Agent — full model list, all endpoints, environment variable reference, design philosophy.
- **DB libraries:** N/A
- **Env vars:** Documents all env vars
- **Write operations:** N/A
- **Runnable:** N/A
- **Risk:** LOW
- **Recommendation:** Keep up to date with every significant change. This is the most important single file in the repo.

---

### Data / Generated Output Files

---

#### `orchid_points.csv`
- **Classification:** `LEGACY` (generated output)
- **Purpose:** 520KB CSV of lat/lon occurrence points — likely generated by a past run of `oc_orchid_atlas.py` or a similar extraction.
- **DB libraries:** N/A
- **Write operations:** N/A
- **Risk:** LOW (static file)
- **Recommendation:** Document as generated output. Not a database backup. Safe to inspect.

---

#### `orchid_climate_profiles.csv`
- **Classification:** `LEGACY` (generated output)
- **Purpose:** CSV output from `orchid_climate_engine.py` — per-genus climate envelope approximations.
- **DB libraries:** N/A
- **Write operations:** N/A
- **Risk:** LOW (static file; approximations, not real climate data)
- **Recommendation:** Document as generated output. Label clearly as math approximation only (latitude-based, not WorldClim).

---

#### `orchid_atlas.html`
- **Classification:** `LEGACY` (generated output)
- **Purpose:** Folium interactive map of orchid occurrences.
- **DB libraries:** N/A
- **Write operations:** N/A
- **Risk:** LOW
- **Recommendation:** Document as generated output. Can be viewed in browser.

---

#### `orchid_atlas_light.html`
- **Classification:** `LEGACY` (generated output)
- **Purpose:** Lighter version of the occurrence atlas map.
- **DB libraries:** N/A
- **Write operations:** N/A
- **Risk:** LOW
- **Recommendation:** Document as generated output.

---

#### `orchid_dump.dump`
- **Classification:** `BROKEN_OR_ORPHANED`
- **Purpose:** Intended as a PostgreSQL dump file. Currently empty (0 bytes).
- **DB libraries:** N/A
- **Write operations:** N/A
- **Risk:** LOW
- **Recommendation:** Document as empty. Do not treat as a backup. A real pg_dump would be megabytes or gigabytes.

---

### Schema / Audit Reference Files

---

#### `record_taxon_map_schema.txt`
- **Classification:** `LEGACY` (archival schema snapshot)
- **Purpose:** PostgreSQL `\d record_taxon_map` output — schema for the `record_taxon_map` table in Neon. Shows FK to `taxa(taxon_id)`.
- **DB libraries:** N/A
- **Write operations:** N/A
- **Risk:** LOW
- **Notable:** References a `taxa` table — this is distinct from `taxonomy_species` (33,786 rows) and `taxonomy_genus` (733 rows) seen in the audit. The `taxa` table has not been directly verified in current Neon schema.
- **Recommendation:** Keep as schema reference. Verify `record_taxon_map` and `taxa` table existence in current Neon before building against them.

---

#### `record_traits_schema.txt`
- **Classification:** `LEGACY` (archival schema snapshot)
- **Purpose:** PostgreSQL `\d record_traits` output — schema for the `record_traits` table in Neon. Shows elevation columns and a **database trigger**.
- **DB libraries:** N/A
- **Write operations:** N/A
- **Risk:** LOW (static)
- **Notable:** **IMPORTANT** — The `record_traits` table has a trigger `record_traits_normalize_elevation` that fires `BEFORE INSERT OR UPDATE OF elev_m`. This means any elevation backfill writing to `record_traits.elev_m` will automatically invoke normalization logic. The elevation infrastructure is more mature than it appears from the surface.
- **Recommendation:** Keep. Read carefully before designing elevation backfill. The trigger is real infrastructure.

---

#### `OC_REPO_INVENTORY_20260224T010114Z.txt`
- **Classification:** `LEGACY` (archival snapshot)
- **Purpose:** Repo inventory generated 2026-02-24 by `oc_repo_inventory.sh`. Documents top-level structure, entrypoints, stack signals.
- **DB libraries:** N/A
- **Write operations:** N/A
- **Risk:** LOW
- **Notable:** Shows the workspace had a React client directory with a folder named after a JSX snippet — indicating a period of experimental frontend work. Git remote points to `https://github.com/jsp1440/orchid-calyx-backend`.
- **Recommendation:** Keep as historical reference.

---

#### `orchid_continuum_db_audit.txt`
- **Classification:** `LEGACY` (archival Neon audit)
- **Purpose:** Full Neon database schema audit from 2026-03-14 04:17. Lists tables by schema: `governance`, `kg`, `neondb_import`, `public`.
- **DB libraries:** N/A
- **Write operations:** N/A
- **Risk:** LOW
- **Notable:** Reveals Neon has multiple schemas beyond `public`: `governance` (communication, repo, work_item tables), `kg` (knowledge graph: entities, literals, relationships), `neondb_import` (harvester, AI, EOL, GBIF tracking tables). These schemas are not visible from `public` queries.
- **Recommendation:** Keep as reference. Read before designing cross-schema queries.

---

#### `orchid_continuum_db_audit_current.txt`
- **Classification:** `LEGACY` (archival Neon audit, most recent)
- **Purpose:** More recent Neon audit from 2026-03-14 04:32 — public schema only. Lists 113 public tables with row counts for 12 key tables.
- **DB libraries:** N/A
- **Write operations:** N/A
- **Risk:** LOW
- **Notable:** As of this audit: `orchid_images` = 1,074,218 rows, `oc_occurrences` = 114,517 rows, `record_media_link` = **1,889,737 rows**, `taxonomy_species` = 33,786, `oc_job_queue` = 739. Also confirms tables: `elevation_backfill_queue`, `source_elevation_backfill_queue`, `trait_elevation`, `orchid_images_old_schema`, `oc_taxa_universe`, `ocu_*` (Orchid Continuum University tables).
- **Recommendation:** Keep. This is the best single reference for the current Neon public schema until a fresh audit is run.

---

### Non-Python Files at Root (not individually classified above)

| File | Classification | Notes |
|---|---|---|
| `alembic/README` | `ACTIVE_SUPPORT` | Generic Alembic README, not customized |
| `alembic/script.py.mako` | `ACTIVE_SUPPORT` | Template for new migration files |
| `alembic/versions/` | `ACTIVE_SUPPORT` | Empty — no migrations exist |
| `tools/introspect_api.py` | `ACTIVE_SUPPORT` | READ-ONLY — inspects FastAPI routes, exports OpenAPI JSON |
| `tools/openapi.json` | `LEGACY` | Generated OpenAPI spec from a past run; may be stale |
| `migrations/` | `ACTIVE_SUPPORT` | Contains 1 SQL migration file |
| `client/` | `LEGACY` | React/Vite stub; no active workflow; not the Calyx frontend |

---

## Summary Statistics

| Classification | Count |
|---|---|
| `ACTIVE_PRODUCTION` | 3 (`app/main.py` entry + `.replit` + `replit.md` + `requirements.txt`) |
| `ACTIVE_SUPPORT` | 8 (`oc_repo_inventory.sh`, `oc_full_system_audit.sh`, `seed.sql`, `migrations/001`, `alembic.ini`, `alembic/env.py`, `README.md`, `app/worker.py`) |
| `LEGACY` | 9 (`oc_system_check_v2.py`, `oc_mission_control.py`, schema/audit .txt files, generated HTML/CSV) |
| `PROTOTYPE` | 6 (`oc_control_panel.py`, `oc_ingestion_tracker.py`, `oc_system_health.py`, `orchid_api.py`, `oc_orchid_atlas.py`, `orchid_climate_engine.py`, `api_occurrence_points.py`) |
| `BROKEN_OR_ORPHANED` | 5 (`alth.py,`, `app → main.py`, `python oc_system_check_v2.py`, `orchid_dump.dump`, `orchid_schema.sql`) |
| `WRITE_CAPABLE_HIGH_RISK` | 5 (`oc_automation_worker.py`, `oc_scheduler.py`, `mission_control_scheduler.py`, `oc_extract_all.py`, `oc_extract_taxonomy.py`) |

---

## Critical Discovery: `alembic/env.py` Points to Neon

`alembic/env.py` line 17:
```python
def get_url():
    return os.getenv("DATABASE_URL", "sqlite:///./calyx.db")
```

**This means:** If `DATABASE_URL` is set (it is, to Neon), and someone runs `alembic upgrade head`, Alembic would execute Calyx model migrations against the Neon production database. Currently this would be a no-op (no files in `alembic/versions/`), but this is a silent trap for any future developer who adds a migration file.

## Critical Discovery: `record_traits` Elevation Trigger

`record_traits_schema.txt` reveals:
```
record_traits_normalize_elevation BEFORE INSERT OR UPDATE OF elev_m, elev_raw_value, elev_parse_method
ON record_traits FOR EACH ROW EXECUTE FUNCTION trg_normalize_elevation()
```

The elevation backfill target table already has normalization logic baked in via a PostgreSQL trigger. The elevation infrastructure in Neon is more developed than previously understood.

## Critical Discovery: `record_media_link` has 1,889,737 Rows

The `orchid_continuum_db_audit_current.txt` shows `record_media_link` with **1,889,737 rows** — nearly 1.9 million media linkages. This table was not previously documented and represents significant catalogued media data beyond `orchid_images`.
