# BUILD 196A — Current State Preservation Index
# Orchid Continuum / Calyx Workspace

**Generated:** 2026-05-03
**Repo:** https://github.com/jsp1440/orchid-calyx-backend
**Branch:** main
**Inspection method:** Static file read only. No SQL executed. No code run.

---

## A. Executive Summary

This Replit workspace hosts **two overlapping systems** that have grown together in a single repository:

1. **Calyx** — An active, production-ready FastAPI backend for orchid show management (entries, judging, volunteers, scoring). This is the primary deliverable being served today. It connects to a Replit-hosted PostgreSQL instance (`PGHOST`/heliumdb) as its operational database.

2. **Orchid Continuum pipeline prototypes** — A collection of root-level Python scripts representing earlier iterations of the harvester engine, occurrence ingestion, taxonomy extraction, climate modeling, and atlas generation. These scripts reference a Neon PostgreSQL database (`DATABASE_URL`) containing over 1 million image records, 302 tables, and real AOS judging data.

**Why preservation is urgent:**
- Root-level OC scripts use an older table schema (`oc_occurrences`, `oc_job_queue`, `oc_harvest_targets`) that may not match the current Neon database structure.
- Several root-level scripts are **write-capable** and connect directly to `DATABASE_URL` (production Neon). Running them accidentally could corrupt or duplicate data.
- The workspace contains no `.env.example`, no separation between active and archived code, and no consistent build numbering below the top level.
- A prior inventory snapshot (`OC_REPO_INVENTORY_20260224T010114Z.txt`) was taken 2026-02-24. The workspace has evolved significantly since then.
- An orphaned file named `app → main.py` (zero bytes, appears to be a corrupted symlink attempt) sits at root alongside active code.

**Active vs. Archived:**
- **Active:** `app/` directory (Calyx API), `replit.md`, `requirements.txt`, `README.md`, `.replit`, `seed.sql`, `migrations/`, `tools/`
- **Likely archival/prototype:** All `oc_*.py` and `orchid_*.py` scripts at root level, `mission_control_scheduler.py`, `api_occurrence_points.py`, `oc_mission_control.py`, `orchid_climate_engine.py`, `oc_control_panel.py`
- **Generated output:** `orchid_atlas.html`, `orchid_atlas_light.html`, `orchid_climate_profiles.csv`, `orchid_dump.dump` (empty), `orchid_schema.sql` (empty), `orchid_points.csv`, `record_taxon_map_schema.txt`, `record_traits_schema.txt`, `tools/openapi.json`
- **Stale audit artifacts:** `OC_REPO_INVENTORY_20260224T010114Z.txt`, `orchid_continuum_db_audit.txt`, `orchid_continuum_db_audit_current.txt`

---

## B. Workspace Map

### Top-Level Structure

```
/
├── app/                    ACTIVE — Calyx FastAPI application
├── alembic/                SCAFFOLDED — not actively used (versions/ is empty)
├── attached_assets/        REFERENCE — AOS PDFs, build spec files, zip archives
├── client/                 STUB — React/Vite frontend, mostly node_modules
├── docs/                   NEW — preservation documents (this build)
├── migrations/             ACTIVE — 1 SQL migration file for reference docs table
├── tools/                  UTILITY — API introspection and OpenAPI export
├── .local/                 REPLIT INTERNAL — agent state, workflow logs, skills
│
├── app/main.py             ACTIVE entrypoint — FastAPI app, startup schema reconciliation
├── app/worker.py           WRITE-CAPABLE — harvest_jobs worker loop (PGHOST)
├── oc_automation_worker.py WRITE-CAPABLE — GBIF harvester (DATABASE_URL, older schema)
├── oc_scheduler.py         WRITE-CAPABLE — job enqueuer (DATABASE_URL, older schema)
├── oc_extract_taxonomy.py  WRITE-CAPABLE — batch UPDATE oc_occurrences (DATABASE_URL)
├── oc_extract_all.py       WRITE-CAPABLE — runs oc_extract_taxonomy.py 30x
├── mission_control_scheduler.py  WRITE-CAPABLE — inserts harvest runs + pipelines (DATABASE_URL)
├── orchid_api.py           READ-ONLY API stub — separate FastAPI for OC data
├── oc_mission_control.py   READ-ONLY — Streamlit dashboard (DATABASE_URL)
├── oc_control_panel.py     READ-ONLY — CLI metrics panel (DATABASE_URL)
├── oc_ingestion_tracker.py READ-ONLY — counts oc_occurrences
├── oc_system_health.py     READ-ONLY — FastAPI health stub for OC
├── oc_system_check_v2.py   READ-ONLY — diagnostic queries (older schema tables)
├── oc_full_system_audit.sh READ-ONLY — shell audit script using psql
├── oc_orchid_atlas.py      READ-ONLY (writes HTML file) — generates folium map
├── orchid_climate_engine.py READ-ONLY (writes CSV) — climate envelope generator
├── oc_extract_taxonomy.py  WRITE-CAPABLE — see above
├── api_occurrence_points.py READ-ONLY — FastAPI stub for occurrence lat/lon
├── oc_repo_inventory.sh    READ-ONLY — generates inventory snapshot
│
├── orchid_atlas.html       GENERATED OUTPUT
├── orchid_atlas_light.html GENERATED OUTPUT
├── orchid_climate_profiles.csv  GENERATED OUTPUT
├── orchid_dump.dump        EMPTY FILE (0 bytes)
├── orchid_schema.sql       EMPTY FILE (0 bytes)
├── orchid_points.csv       GENERATED OUTPUT
├── record_taxon_map_schema.txt  SCHEMA NOTES
├── record_traits_schema.txt     SCHEMA NOTES
├── OC_REPO_INVENTORY_20260224T010114Z.txt  ARCHIVAL SNAPSHOT (2026-02-24)
├── orchid_continuum_db_audit.txt           ARCHIVAL AUDIT
├── orchid_continuum_db_audit_current.txt   ARCHIVAL AUDIT
├── alth.py,                ORPHANED — duplicate health router, comma in filename
├── app → main.py           ORPHANED — zero-byte corrupted file
├── python oc_system_check_v2.py  ORPHANED — filename with space/shell prefix
```

### `app/` Subdirectory (Calyx — Active)

```
app/
├── main.py         FastAPI entry, CORS, startup schema reconciliation
├── database.py     DB engine config (prefers PGHOST, falls back to DATABASE_URL)
├── models.py       SQLAlchemy models (32 tables on heliumdb)
├── schemas.py      Pydantic request/response schemas
├── security.py     API key auth, judge auth (X-Judge-Id header)
├── deps.py         get_db dependency
├── storage.py      File storage with SHA256 hashing
├── worker.py       Harvest job worker loop (connects to get_engine/PGHOST)
├── routers/
│   ├── health.py          GET /health
│   ├── tiles.py           GET /api/tiles/registry
│   ├── shows.py           Shows CRUD
│   ├── entries.py         Entries CRUD
│   ├── volunteers.py      Legacy volunteer tasks
│   ├── awards.py          Awards CRUD
│   ├── calyx_core.py      Orgs, contacts, events, templates
│   ├── reference_docs.py  AOS PDF reference documents
│   ├── judging.py         Full judging system + scorecard workflow
│   ├── volunteer_ops.py   Roles, shifts, assignments, Excel import/export
│   └── feedback.py        Beta feedback capture
└── services/              Directory exists; harvester_engine.py removed
```

---

## C. Critical Systems Inventory

### Calyx (Show Management API)
- **Location:** `app/`
- **Status:** Active, running on port 3000 via uvicorn
- **Database:** PGHOST → heliumdb (32 tables, Replit-hosted PostgreSQL)
- **Key files:** `app/main.py`, `app/models.py`, `app/routers/judging.py`
- **Deployment:** Configured in `.replit` as `deploymentTarget = "autoscale"`

### Orchid Continuum Harvester Engine
- **Root-level prototypes:** `oc_automation_worker.py`, `oc_scheduler.py`, `mission_control_scheduler.py`
- **Status:** Not running. All harvesters in Neon show `error` or `disabled` status.
- **Database target:** DATABASE_URL (Neon) via older schema (`oc_job_queue`, `oc_harvest_targets`, `oc_occurrences`)
- **Risk:** These scripts may write to tables that no longer exist or have changed schema in Neon.
- **Correct home:** Orchid Continuum repo (not this Calyx repo)

### Taxonomy / Identity Layer
- **Scripts:** `oc_extract_taxonomy.py` (UPDATE oc_occurrences), `oc_extract_all.py` (30-batch loop), `oc_system_check_v2.py` (queries oc_taxa, oc_occurrence_records)
- **Status:** Prototype-era. References `oc_taxa`, `oc_occurrence_records` — table names differ from current Neon schema (`orchid_images`, `judging_criteria`, etc.)
- **Neon reality:** `orchid_images` has 1,096,958 rows; taxonomy linked via `taxonomy_id` FK

### Image Pipeline / Media Harvesting
- **Neon tables (observed):** `orchid_images` (1.1M rows, 0 downloaded), `eol_images` (95K rows, 6,842 downloaded), `image_assets` (84), `image_validation_results` (429)
- **Harvester scripts (root):** Reference older `oc_images` table name (not current)
- **Backup tables:** `backup_orchid_images_record_link_fix` (366,807), `backup_orchid_images_unlinked_taxonomy_fix` (424,307)
- **Status:** Pipeline stalled. No active downloader running in this repo.

### Elevation Backfill
- **Evidence in code:** `oc_full_system_audit.sh` references `elevation_lookup_log`, `elevation_backfill_queue`
- **Neon reality:** Only 1,036 of 1,096,958 orchid_images rows have `elevation_meters` populated (0.09%)
- **Status:** Not implemented in this repo. Belongs in Orchid Continuum repo.

### GBIF Occurrence Rehydration
- **Neon queues:** `gbif_occurrence_rehydrate_queue` (257,227), `gbif_occurrence_rehydrate_queue_v2` (262,241), results (9,058 done)
- **Key refetch queue:** 245,705 rows pending
- **Status:** Queues populated but no active worker running in this repo.

### Climate Engine
- **File:** `orchid_climate_engine.py`
- **Status:** Generates approximate climate envelopes from lat/lon only (no actual climate API). Writes `orchid_climate_profiles.csv`. Read-only against DB, write to local CSV.
- **Output:** `orchid_climate_profiles.csv` present in repo.

### Atlas / Map Generation
- **Files:** `oc_orchid_atlas.py`, `orchid_api.py`, `api_occurrence_points.py`
- **Outputs:** `orchid_atlas.html`, `orchid_atlas_light.html`
- **Status:** Prototype. Writes HTML files locally. Read-only against DB.

### Mission Control / Scheduler
- **Files:** `oc_mission_control.py` (Streamlit dashboard), `mission_control_scheduler.py` (hourly loop), `oc_scheduler.py` (job enqueuer)
- **Status:** Not running. `mission_control_scheduler.py` if run would INSERT into `oc_harvest_runs` and `pipeline_runs` on DATABASE_URL every hour.

### Governance
- **Status:** `app/routers/governance.py` and `app/services/harvester_engine.py` were removed in the current session (Build 196A context). Stale `.pyc` for governance remains in `__pycache__` (harmless).

### Backend / API Services
- **Active:** `app/main.py` → uvicorn on port 3000
- **Stale alternates:** `orchid_api.py` (separate FastAPI), `oc_system_health.py` (separate FastAPI stub), `api_occurrence_points.py` (separate FastAPI stub) — none of these are registered in the workflow

### Replit Configuration
- **File:** `.replit`
- **Workflow:** `Calyx API` runs `uvicorn app.main:app --host 0.0.0.0 --port 3000` (console output type)
- **Deployment:** autoscale, same uvicorn command with `${PORT:-3000}`
- **Ports mapped:** 3000 (API), 5173 (unused), 8000, 8080, 8501 (Streamlit — not used)
- **Runtime:** nodejs-20, python-3.11, postgresql-16

### Neon / PostgreSQL Access
- **DATABASE_URL:** Neon (Orchid Continuum) — 302 tables, 1M+ rows, real AOS data
- **PGHOST:** heliumdb (Replit-hosted) — 32 tables, Calyx operational data
- **App uses:** `app/database.py` prefers PGHOST for Calyx operations
- **OC scripts use:** DATABASE_URL directly via psycopg2/psycopg

### AOS Reference Documents
- **Location:** `attached_assets/` — 12 PDF files (AOS scoring cards, judging forms, style book, clonal name designations, terminology)
- **API:** `app/routers/reference_docs.py` serves these via `/api/reference-docs` and `/api/admin/reference-docs`

### Alembic
- **Location:** `alembic/`, `alembic.ini`
- **Status:** Scaffolded but empty — `alembic/versions/` contains no migration files. Schema management is done via `Base.metadata.create_all()` + `_safe_add_column()` in `app/main.py`.

### Client (Frontend Stub)
- **Location:** `client/`
- **Status:** React/Vite project with `node_modules` installed but no active workflow. Not used by Calyx (frontend is Famous AI, separate project).

---

## D. Write-Capable Components

The following files can write to a database or modify data. Listed in order of risk.

| File | Write Operations | Target DB | Risk |
|------|-----------------|-----------|------|
| `oc_extract_all.py` | Calls `oc_extract_taxonomy.py` 30 times | DATABASE_URL (Neon) | **HIGH** — 30-batch UPDATE of oc_occurrences |
| `oc_extract_taxonomy.py` | `UPDATE oc_occurrences SET species_id, genus_id, country, elevation_m` (5000 rows/run) | DATABASE_URL (Neon) | **HIGH** — bulk UPDATE, no dry-run |
| `mission_control_scheduler.py` | `INSERT INTO oc_harvest_runs`, `INSERT INTO pipeline_runs`, runs hourly loop | DATABASE_URL (Neon) | **HIGH** — infinite loop, inserts every hour |
| `oc_scheduler.py` | `INSERT INTO oc_job_queue`, `UPDATE oc_harvest_targets SET state='processing'` | DATABASE_URL (Neon) | **HIGH** — infinite loop, FOR UPDATE SKIP LOCKED |
| `oc_automation_worker.py` | `INSERT INTO oc_occurrences`, `UPDATE oc_job_queue SET status='running'/'completed'` | DATABASE_URL (Neon) | **HIGH** — infinite loop, bulk INSERT |
| `app/worker.py` | `UPDATE harvest_jobs SET status='running'/'done'`, `FOR UPDATE SKIP LOCKED` | PGHOST (heliumdb) | **MEDIUM** — worker loop, but only touches harvest_jobs on heliumdb |
| `seed.sql` | `INSERT INTO` organizations, shows, entries, volunteer_roles, shifts, volunteers, assignments, judges, score_submissions, awards | PGHOST (heliumdb) | **LOW** — demo seed, uses `ON CONFLICT DO NOTHING` |
| `migrations/001_create_system_reference_documents.sql` | `CREATE TABLE`, `CREATE INDEX` | Any | **LOW** — idempotent DDL with `IF NOT EXISTS` |

**Additional write signals detected:**
- `oc_automation_worker.py` line 62: `INSERT INTO oc_occurrences`
- `oc_scheduler.py` line 12: `INSERT INTO oc_job_queue`
- `oc_scheduler.py` line 37: `UPDATE oc_harvest_targets SET state='processing'`
- `mission_control_scheduler.py` line 17: `INSERT INTO oc_harvest_runs`
- `mission_control_scheduler.py` line 38: `INSERT INTO pipeline_runs`
- `oc_extract_taxonomy.py` line 35: `UPDATE oc_occurrences SET species_id, genus_id, country, elevation_m`
- `app/worker.py` line 22: `UPDATE harvest_jobs SET status='running'`
- `app/worker.py` line 33: `UPDATE harvest_jobs SET status='done'`
- `app/main.py`: `Base.metadata.create_all()` and `ALTER TABLE` via `_safe_add_column()` on startup

**Not currently write-capable (read-only):**
- `oc_control_panel.py`, `oc_ingestion_tracker.py`, `oc_system_check_v2.py`, `oc_full_system_audit.sh`, `oc_repo_inventory.sh`, `oc_mission_control.py` (SELECT only)
- `orchid_climate_engine.py` (writes CSV, not DB), `oc_orchid_atlas.py` (writes HTML, not DB)

---

## E. Documentation Inventory

| File | Type | Status | Notes |
|------|------|--------|-------|
| `README.md` | API reference | Active, but outdated | Only covers early Calyx endpoints; missing judging, volunteers, scorecards |
| `replit.md` | Architecture memory | Active, comprehensive | Best single source of truth for Calyx; includes full endpoint reference |
| `OC_REPO_INVENTORY_20260224T010114Z.txt` | Snapshot | Archival | Taken 2026-02-24; workspace has changed significantly since |
| `orchid_continuum_db_audit.txt` | DB audit | Archival | Static snapshot, date unknown |
| `orchid_continuum_db_audit_current.txt` | DB audit | Archival | "Current" is relative; likely stale |
| `record_taxon_map_schema.txt` | Schema notes | Uncertain | Static schema notes, currency unknown |
| `record_traits_schema.txt` | Schema notes | Uncertain | Static schema notes, currency unknown |
| `tools/openapi.json` | OpenAPI spec | Generated | Reflects last run of `tools/introspect_api.py`; may be stale |
| `alembic/README` | Alembic docs | Scaffolded | Generic Alembic readme; not customized |
| `migrations/001_create_system_reference_documents.sql` | Migration | Active | Single manual migration for reference docs table |
| `attached_assets/*.pdf` | AOS reference | Active | 12 PDF files: scoring cards, judging forms, style book, terminology |
| `attached_assets/Pasted-*.txt` | Build specs | Archival | Historical build instruction documents |
| `docs/preservation/` | Preservation | NEW (this build) | Created by Build 196A |

---

## F. Preservation Risks

**Risk 1 — Write-capable OC scripts mixed with active Calyx code (CRITICAL)**
`oc_extract_all.py`, `oc_scheduler.py`, `oc_automation_worker.py`, and `mission_control_scheduler.py` can all write to the Neon production database (DATABASE_URL). They sit in the root directory alongside active Calyx files with no labeling, README, or guard to prevent accidental execution. Running `oc_extract_all.py` would issue 30 batches of 5,000-row UPDATE statements against Neon.

**Risk 2 — Stale schema in OC prototype scripts (HIGH)**
Root-level OC scripts reference table names (`oc_occurrences`, `oc_job_queue`, `oc_harvest_targets`, `oc_taxa`, `oc_occurrence_records`, `oc_images`, `oc_harvesters`, `oc_harvester_runs`) that do not match the current Neon schema (`orchid_images`, `harvest_jobs`, `harvesters`, etc.). If run, they would either fail silently or write to wrong/missing tables.

**Risk 3 — No .env.example file (HIGH)**
There is no `.env.example` or documented list of all required environment variables with safe defaults. `DATABASE_URL` (Neon production) and `PGHOST`/`PGPASSWORD`/`PGDATABASE` (heliumdb) are both live credentials. Any developer onboarding blind could inadvertently point to production.

**Risk 4 — Three orphaned/broken files at root (MEDIUM)**
- `alth.py,` — filename includes a literal comma; is a duplicate health router
- `app → main.py` — zero-byte file, appears to be a failed symlink attempt
- `python oc_system_check_v2.py` — filename includes shell prefix `python `, cannot be imported

**Risk 5 — Two parallel FastAPI apps exist but only one is registered (MEDIUM)**
`orchid_api.py` and `oc_system_health.py` are both full FastAPI applications connecting to DATABASE_URL. Neither is registered in `.replit` workflows. If accidentally started they would expose unprotected read endpoints against Neon with no API key auth.

**Risk 6 — Alembic scaffolded but unused; schema management is implicit (MEDIUM)**
`alembic/versions/` is empty. Schema changes are applied via `create_all()` + `_safe_add_column()` at startup. No migration history exists. This makes it impossible to audit what schema changes have been applied or roll them back.

**Risk 7 — `orchid_dump.dump` and `orchid_schema.sql` are empty files (LOW)**
Both are 0 bytes. Their presence suggests a dump or schema export was intended but never completed. They may mislead a future developer into thinking a backup exists.

**Risk 8 — Client frontend is orphaned (LOW)**
`client/` contains a React/Vite project with node_modules but no active workflow. The frontend for Calyx is described as "Famous AI (separate project)" in replit.md. The client directory adds noise and confusion about what is served.

---

## G. Recommended Reading Order

### Jeff (project owner)
1. `docs/preservation/build_196A_start_here.md` — one-page orientation
2. `replit.md` — full architecture and endpoint reference
3. This document (Section F — Preservation Risks)
4. Section D (Write-Capable Components) — understand what must not be run accidentally

### Replit Agent
1. `replit.md` — authoritative project memory
2. `app/main.py` — entry point and startup behavior
3. `app/models.py` — all database models
4. `app/routers/judging.py` — most complex router
5. This document (Section C — Critical Systems Inventory)

### Julius (AI data analysis)
1. Section B (Workspace Map) — understand the two-database architecture
2. Section C (image pipeline and occurrence sections)
3. `replit.md` (Database Models section)
4. `orchid_continuum_db_audit_current.txt` — Neon table inventory

### External Advisor
1. `docs/preservation/build_196A_start_here.md`
2. `README.md` — public-facing API overview
3. Section A (Executive Summary)
4. Section H (Recommended Next Builds)

### Fiscal Sponsor / Grant Reviewer
1. `docs/preservation/build_196A_start_here.md`
2. Section A (Executive Summary — what exists and why it matters)
3. Section C (image pipeline: 1.1M records, real AOS data, GBIF/iNaturalist/EOL sources)
4. Section H (Recommended Next Builds — roadmap)

### Future Developer
1. `docs/preservation/build_196A_start_here.md`
2. `replit.md`
3. `README.md`
4. `app/main.py` → `app/models.py` → `app/routers/`
5. This document in full, especially Sections D and F before touching anything at root level

---

## H. Recommended Next Builds

Ranked by impact and safety. All builds below are scoped to the Orchid Continuum repo (not Calyx) unless noted.

---

**Build 197 — Orchid Continuum: Root-Level Script Triage**
- Purpose: Label, quarantine, or document every root-level `.py` file. Create `scripts/legacy/` and `scripts/active/` folders conceptually (do not move files without approval). Add a `SCRIPTS_INDEX.md` at root explaining each file's status, target DB, and write risk.
- Risk: **Low** (documentation only)
- Database touch: No
- Code changes: No (docs only)
- Safe for Replit tonight: Yes

---

**Build 198 — Orchid Continuum: Harvester Engine — Schema Alignment Audit**
- Purpose: Compare root-level OC script table names against actual Neon schema. Produce a mapping doc: `oc_occurrences` → `orchid_images`? `oc_taxa` → where? Identify what's missing.
- Risk: **Low** (read-only inspection)
- Database touch: Read-only SELECT
- Code changes: No
- Safe for Replit tonight: Yes

---

**Build 199 — Orchid Continuum: Elevation Backfill — Design and Queue**
- Purpose: Design the elevation backfill pipeline for `orchid_images.elevation_meters` (currently 1,036 of 1,096,958 rows populated). Identify the API source (Open-Elevation, Google Elevation, etc.), design the batch queue, write the implementation plan.
- Risk: **Medium** (will eventually write to Neon, but this build is design-only)
- Database touch: No (design build)
- Code changes: No
- Safe for Replit tonight: Yes

---

**Build 200 — Orchid Continuum: Image Download Pipeline — First 10,000**
- Purpose: Build a controlled downloader for `orchid_images` records with `download_status IS NULL`, starting with a batch of 10,000 (non-GBIF_NON_ORCHID rows first). Store to Google Drive or local path. Update `download_status`, `local_path`, `file_sha256`.
- Risk: **Medium** (writes to Neon, external API calls)
- Database touch: Yes (UPDATE orchid_images)
- Code changes: Yes (new script in OC repo)
- Safe for Replit tonight: Only the design phase

---

**Build 201 — Calyx: README Refresh**
- Purpose: Update `README.md` to reflect the current full API surface (judging system, scorecard workflow, volunteer ops, AOS criteria). Currently describes only the early Calyx endpoints.
- Risk: **None**
- Database touch: No
- Code changes: Documentation only
- Safe for Replit tonight: Yes

---

**Build 202 — Calyx: Add .env.example**
- Purpose: Create `.env.example` with all required and optional environment variables, safe placeholder values, and comments. Prevents accidental production credential exposure.
- Risk: **None**
- Database touch: No
- Code changes: New file only
- Safe for Replit tonight: Yes

---

**Build 203 — Orchid Continuum: Harvester Status API (read-only)**
- Purpose: Add a Calyx read-only endpoint `GET /api/oc/status` that reads harvester status, orchid_images counts by download_status, and GBIF queue depth from Neon. No writes. Gives Famous AI frontend visibility into OC pipeline health.
- Risk: **Low** (read-only, no new writes)
- Database touch: Read-only (Neon via DATABASE_URL)
- Code changes: New router in Calyx
- Safe for Replit tonight: Yes

---

**Build 204 — Orchid Continuum: GBIF Non-Orchid Purge Plan**
- Purpose: 366,807 rows in `orchid_images` are flagged `GBIF_NON_ORCHID`. Design a safe audit and purge strategy. Document the criteria used to flag them. Propose archival vs. deletion.
- Risk: **Low** (design/audit only; no deletions in this build)
- Database touch: Read-only audit
- Code changes: No
- Safe for Replit tonight: Yes (audit only)

---

**Build 205 — Orchid Continuum: Taxonomy Identity Layer**
- Purpose: Map current Neon taxonomy tables to a stable identity model. Understand `taxonomy_id` FK in `orchid_images`, enumerate distinct taxonomy tables, assess completeness. Design the canonical taxonomy record.
- Risk: **Low** (read and design)
- Database touch: Read-only
- Code changes: No
- Safe for Replit tonight: Yes

---
