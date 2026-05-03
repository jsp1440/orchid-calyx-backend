# BUILD 199 — Emergency Legacy Script Safety Lock
# Orchid Continuum / Calyx Workspace

**Generated:** 2026-05-03
**Type:** Code guard — no database touched, no scripts run, no SQL executed.
**Companion builds:** Build 197 (script triage), Build 198 (schema alignment audit)

---

## What Was Done

A fail-closed safety guard was prepended to 8 root-level Python scripts. The guard halts execution immediately unless a specific environment variable is set to an exact string. No file was deleted, renamed, moved, or restructured. The guard is the first thing each script evaluates — before any database import, connection, or logic runs.

---

## Guard Pattern Applied

```python
import os
import sys

if os.getenv("OC_ALLOW_LEGACY_OC_SCRIPT_RUN") != "YES_I_UNDERSTAND_THIS_CAN_WRITE_TO_PRODUCTION":
    print("BLOCKED: This legacy Orchid Continuum/Calyx root-level script is write-capable or schema-stale and is disabled by default.")
    print("This safety guard prevents accidental production database writes.")
    print("To run intentionally, set OC_ALLOW_LEGACY_OC_SCRIPT_RUN=YES_I_UNDERSTAND_THIS_CAN_WRITE_TO_PRODUCTION after manual review.")
    sys.exit(2)
```

Exit code `2` is used (distinct from `0` = success and `1` = error) so automated systems can detect a deliberate safety block vs. a crash.

---

## Files Guarded (8)

| File | Primary Risk | Guard Position |
|---|---|---|
| `oc_extract_taxonomy.py` | **CRITICAL** — Connects and executes UPDATE at module load (top-level code, no `__main__` guard). Bulk UPDATE `oc_occurrences` (5,000 rows/run) on Neon production. | Before `import psycopg2` and before top-level `conn = psycopg2.connect(DB)` |
| `oc_extract_all.py` | **CRITICAL** — Runs `oc_extract_taxonomy.py` 30 times via subprocess. Up to 150,000 row UPDATEs. | Before `import subprocess` and before the loop |
| `oc_automation_worker.py` | **CRITICAL** — Infinite loop. INSERTs into `oc_occurrences` and UPDATEs `oc_job_queue` on Neon. | Before `import psycopg` |
| `mission_control_scheduler.py` | **CRITICAL** — Infinite hourly loop. INSERTs into `oc_harvest_runs` and `pipeline_runs` on Neon every 3600s. | Before `import psycopg2` |
| `oc_scheduler.py` | **CRITICAL** — Infinite loop. UPDATEs `oc_harvest_targets` and INSERTs into `oc_job_queue` on Neon. | Before `import psycopg` |
| `oc_system_check_v2.py` | **HIGH** — Schema-stale. All 7 table names it queries no longer exist in current Neon schema. Running it causes cascading rollback errors. | Before `import psycopg2` and before top-level print/connect calls |
| `orchid_api.py` | **MEDIUM** — Standalone FastAPI with no authentication. If started with `uvicorn`, exposes unguarded read endpoints against Neon. | Before `import psycopg2` and before `FastAPI()` instantiation |
| `oc_system_health.py` | **MEDIUM** — Same as `orchid_api.py` — standalone unauth'd FastAPI querying Neon. | Before `import psycopg2` and before `FastAPI()` instantiation |

---

## Files Not Found / Skipped (0)

All 8 target files were found and guarded. No file was missing.

---

## Why Each File Was Guarded

### Write-capable scripts (would modify Neon production data)

**`oc_extract_taxonomy.py`** — The most dangerous file in the repo. It runs `UPDATE oc_occurrences SET species_id, genus_id, country, elevation_m` against Neon immediately on any invocation. There is no `if __name__ == '__main__'` guard — importing the module triggers the write path. Column schema alignment with current Neon `oc_occurrences` is unverified (Build 198, Section 4).

**`oc_extract_all.py`** — A force multiplier for `oc_extract_taxonomy.py`. Runs it 30 times in sequence via subprocess, yielding up to 150,000 row UPDATEs against Neon with no dry-run, no confirmation, no rollback.

**`oc_automation_worker.py`** — Infinite loop that picks GBIF harvest jobs from `oc_job_queue` and INSERTs occurrence records into `oc_occurrences`. Column schema of `oc_occurrences` INSERT target is unverified. `oc_harvest_targets.genus` column existence unverified (Build 198, Section 4).

**`oc_scheduler.py`** — Infinite loop that UPDATEs `oc_harvest_targets.state` to `'processing'` and INSERTs new jobs into `oc_job_queue`. Column schema of `oc_harvest_targets` unverified.

**`mission_control_scheduler.py`** — Infinite hourly loop that INSERTs into `oc_harvest_runs` and `pipeline_runs` every 3,600 seconds until killed. Additionally, `pipeline_runs` exists in two Neon schemas (`public` and `oc_mission_control`) — this script would write to `public.pipeline_runs` by default, which may not be the intended target (Build 198, Section 3 — Critical Discovery 1).

### Schema-stale scripts (all queries would fail against current Neon)

**`oc_system_check_v2.py`** — Every table it queries is stale: `oc_occurrence_records`, `oc_images`, `oc_taxa`, `oc_atlas_cells`, `oc_traits`, `oc_harvesters`, `oc_harvester_runs`. None of these table names exist in the current Neon public schema. The script handles errors with `conn.rollback()` per query, so it will not crash — but it will silently return zero results for every check, which is worse than a clear block because it gives false confidence in an "all-clear" health check. (Build 198, Section 2)

### Unguarded API servers (would expose production data without auth if started)

**`orchid_api.py`** — Full standalone FastAPI app with `allow_origins=["*"]` CORS and no API key authentication. If started via `uvicorn orchid_api:app`, it exposes live Neon occurrence data publicly. Not registered in any Replit workflow, but nothing prevents accidental `uvicorn` invocation.

**`oc_system_health.py`** — Same class of risk. Standalone FastAPI with no auth, connects to Neon.

---

## How to Override (Intentionally)

Set the environment variable before running:

```bash
export OC_ALLOW_LEGACY_OC_SCRIPT_RUN=YES_I_UNDERSTAND_THIS_CAN_WRITE_TO_PRODUCTION
python oc_extract_taxonomy.py
```

Or inline for a single run:

```bash
OC_ALLOW_LEGACY_OC_SCRIPT_RUN=YES_I_UNDERSTAND_THIS_CAN_WRITE_TO_PRODUCTION python oc_scheduler.py
```

The variable must match the string exactly — any typo, truncation, or case difference leaves the guard active.

**The variable is not set in any Replit environment secret.** It must be set manually in a shell session. It will not persist between sessions unless explicitly added. This is intentional — each session requires a deliberate act to unlock.

---

## IMPORTANT: Override Should Only Happen After

Before setting the override variable and running any of these scripts, the following must be completed:

1. **Column-level schema verification (Build 199 / Julius)** — Confirm that `oc_occurrences`, `oc_harvest_targets`, `oc_harvest_runs`, and `oc_job_queue` column names match what the scripts expect. This is the blocking prerequisite for all write-capable scripts. See Build 198, Section 4 and Section 9.

2. **`pipeline_runs` schema disambiguation** — Confirm whether `mission_control_scheduler.py` should target `public.pipeline_runs` or `oc_mission_control.pipeline_runs`. These are two different tables in two different schemas.

3. **`oc_system_check_v2.py` rewrite** — All 7 table references must be updated to current schema names before this script can provide meaningful health data.

4. **`orchid_api.py` / `oc_system_health.py` auth** — API key authentication must be added before either server is exposed.

5. **Explicit human sign-off** — Any run of a write-capable script against Neon production requires deliberate human review. The `oc_extract_taxonomy.py` + `oc_extract_all.py` combination in particular should never run without a recovery plan for the rows it will modify.

---

## Scripts NOT Guarded (and Why)

These scripts were not in the target list and remain unguarded. They are lower-risk based on Build 197 and 198 analysis.

| File | Reason Not Guarded |
|---|---|
| `oc_mission_control.py` | Streamlit dashboard — read-only SELECT only; requires `streamlit run` to activate, not a passive risk |
| `oc_control_panel.py` | CLI metrics — read-only SELECT only; wraps all queries in try/except |
| `oc_ingestion_tracker.py` | Single COUNT query — read-only; exits on completion |
| `oc_orchid_atlas.py` | Read-only SELECT; writes HTML file to local disk only |
| `orchid_climate_engine.py` | Read-only SELECT; writes CSV to local disk only |
| `api_occurrence_points.py` | Read-only FastAPI stub; single endpoint; low risk compared to `orchid_api.py` |
| `oc_repo_inventory.sh` | Shell script; no DB connection |
| `oc_full_system_audit.sh` | Shell script; SELECT COUNT only; each query wrapped with `|| echo "missing"` |

Note: `oc_mission_control.py`, `oc_control_panel.py`, and `oc_ingestion_tracker.py` connect to `DATABASE_URL` at import/run time but perform no writes. They remain usable as read-only diagnostic tools.

---

## No Database Commands Were Run

This build performed no SQL queries, no database connections, no migrations, no schema changes, and no data modifications of any kind. All changes are limited to prepending Python code to 8 files. The Calyx API (heliumdb) and Neon production database are untouched.

---

## Recommended Next Step

**Build 199B (Julius) — Column-Level Schema Verification**

Run `\d` (schema describe) queries against Neon for the following tables:

```
\d oc_occurrences
\d oc_harvest_targets
\d oc_harvest_runs
\d oc_job_queue
\d records
\d record_media_link
\d elevation_backfill_queue
\d source_elevation_backfill_queue
\d oc_taxa_universe
\d oc_core.taxa
\d oc_mission_control.pipeline_runs
\d public.pipeline_runs
SELECT table_name, column_name, data_type FROM information_schema.columns
WHERE table_schema = 'public' AND table_name IN (
  'oc_occurrences', 'oc_harvest_targets', 'oc_harvest_runs', 'oc_job_queue'
) ORDER BY table_name, ordinal_position;
```

Deliver as `docs/preservation/build_199B_column_schemas.md`.

This is the prerequisite that unblocks all 5 currently blocked scripts and gates all future OC pipeline work.
