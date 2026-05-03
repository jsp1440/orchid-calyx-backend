# BUILD 197 — Root Script Start Here
# One-Page Triage Guide for Root-Level Files

**Generated:** 2026-05-03
**Companion to:** `build_197_root_level_script_triage.md`

---

## Top 10 Files NOT to Run Casually

In order of danger. Do not execute any of these without deliberate, reviewed intent.

| # | File | Why Dangerous |
|---|---|---|
| 1 | `oc_extract_all.py` | Runs `oc_extract_taxonomy.py` 30 times — up to 150,000 row UPDATEs on Neon with no confirmation prompt |
| 2 | `oc_automation_worker.py` | Infinite loop — bulk INSERTs into `oc_occurrences` on Neon, `FOR UPDATE SKIP LOCKED` on job queue |
| 3 | `mission_control_scheduler.py` | Infinite hourly loop — INSERTs into `oc_harvest_runs` and `pipeline_runs` on Neon every 3600s until killed |
| 4 | `oc_scheduler.py` | Infinite loop — UPDATEs `oc_harvest_targets` and INSERTs into `oc_job_queue` on Neon |
| 5 | `oc_extract_taxonomy.py` | Batch UPDATE of `oc_occurrences` (5,000 rows/run) on Neon with no dry-run or rollback guard |
| 6 | `alembic/env.py` (via `alembic upgrade`) | Points to `DATABASE_URL` (Neon) by default — any future migration file would run DDL against production |
| 7 | `app/worker.py` (via `python -m app.worker`) | Infinite loop writing to `harvest_jobs` on heliumdb — placeholder logic only, no real handler |
| 8 | `orchid_api.py` (via uvicorn) | Standalone FastAPI with no auth — exposes unguarded read endpoints against Neon if started |
| 9 | `oc_system_health.py` (via uvicorn) | Same — standalone unauth'd FastAPI against Neon |
| 10 | `oc_ingestion_tracker.py` | Connects to `DATABASE_URL` and executes at import time — will fail loudly if schema differs |

---

## Safest Files to Read First

These are read-only, informative, and carry no execution risk.

| File | What You'll Learn |
|---|---|
| `replit.md` | Full architecture, all 32 Calyx models, every API endpoint, env var reference — the authoritative project memory |
| `docs/preservation/build_196A_current_state_preservation_index.md` | Full workspace map, write-risk analysis, recommended reading order by role |
| `docs/preservation/build_197_root_level_script_triage.md` | This build — full per-file classification |
| `README.md` | Public-facing API overview (partially outdated — missing judging/volunteer ops sections) |
| `orchid_continuum_db_audit_current.txt` | Best current snapshot of Neon public schema — 113 tables, row counts for key tables as of 2026-03-14 |
| `record_traits_schema.txt` | Shows the `record_traits` elevation trigger — important before designing elevation backfill |
| `orchid_continuum_db_audit.txt` | Reveals Neon has additional schemas beyond `public`: `governance`, `kg`, `neondb_import` |
| `seed.sql` | Shows the Calyx demo data model — safe to read, idempotent if run |
| `oc_full_system_audit.sh` | Read-only psql health check — safe to read or run |
| `oc_repo_inventory.sh` | Read-only repo snapshot generator — safe to read or run |

---

## What Replit Agent Should Handle

These tasks are within Replit Agent's safe operating zone in this repo.

**Safe to ask Replit Agent tonight:**
- Add, fix, or extend endpoints in `app/routers/`
- Update `app/models.py`, `app/schemas.py`, or `app/security.py`
- Update `replit.md` or `README.md`
- Add `.env.example` with placeholder values
- Fix duplicates in `requirements.txt`
- Add a comment to `alembic.ini` warning against running migrations
- Create new files in `docs/`
- Run `tools/introspect_api.py` to inspect routes
- Run `oc_full_system_audit.sh` or `oc_repo_inventory.sh` (read-only)
- Query heliumdb (PGHOST) for Calyx data
- Read-only inspection queries against Neon (DATABASE_URL)
- Restart the Calyx API workflow

**Requires explicit approval first:**
- Any modification to root-level `oc_*.py` or `orchid_*.py` scripts
- Starting or modifying `alembic/` in any way
- Adding new routes that connect to `DATABASE_URL` directly
- Touching `.replit` deployment config
- Any write operation against Neon

**Do not ask Replit Agent to:**
- Run `oc_extract_all.py`, `oc_automation_worker.py`, `oc_scheduler.py`, or `mission_control_scheduler.py`
- Run `alembic upgrade head` or any Alembic migration command
- Activate harvesters, scrapers, or the elevation backfill pipeline
- Delete, rename, or archive any root-level files without explicit written approval

---

## What Julius Should Handle

These require large-scale data analysis, batch computation, or cross-table reasoning beyond Replit Agent's scope.

| Task | Why Julius |
|---|---|
| Elevation backfill for 1M+ `orchid_images` rows | Large batch job; needs API rate limiting, error handling, resumability |
| GBIF rehydration queue analysis (257K rows) | Complex join and status analysis across multiple queue tables |
| `record_media_link` analysis (1.89M rows) | Volume requires columnar analysis, not row-by-row inspection |
| Taxonomy identity reconciliation | Cross-table joins across `taxonomy_species`, `taxonomy_genus`, `oc_taxa_universe`, `taxonomy_*` tables |
| Image deduplication via perceptual hash | Batch comparison of 1M+ rows |
| `oc_occurrences` vs `orchid_images` schema mapping | Understand whether these are separate datasets or overlapping |
| `neondb_import` schema exploration | 30+ tables in a separate Neon schema — needs systematic profiling |
| `kg` schema (knowledge graph) analysis | `kg_entity`, `kg_literal`, `kg_relationship` tables need graph-aware reasoning |

---

## What Should Wait for Manual Review

These decisions carry enough consequence that they should not be delegated to any automated agent.

| Decision | Why Manual |
|---|---|
| Whether to run `oc_extract_taxonomy.py` | Updates `oc_occurrences` in Neon — need to verify schema match first |
| Activating any infinite-loop worker | Requires oversight; infinite loops must not run unattended against production |
| Alembic migration strategy | Decision: continue using `_safe_add_column()` or switch to Alembic — has major schema governance implications |
| `orchid_dump.dump` — request a real pg_dump | Currently 0 bytes. A real Neon backup requires manual `pg_dump` with correct credentials |
| Purging `GBIF_NON_ORCHID` rows (366K records) | Deletion at this scale requires human sign-off |
| `governance` and `kg` schema access | These Neon schemas may have access restrictions or governance implications |
| `ocu_*` tables (Orchid Continuum University) | Unknown context — do not modify without understanding their role |
| Client frontend (`client/`) — keep or remove | Decision requires understanding what Famous AI replaces and whether the client stub has any value |

---

## Two-Minute Orientation

```
WHAT IS RUNNING:
  Calyx API (uvicorn, port 3000)
  → app/main.py → app/routers/ → heliumdb (PGHOST)
  → reads judging_awards/judging_criteria from Neon (DATABASE_URL)

WHAT IS NOT RUNNING BUT EXISTS IN THIS REPO:
  oc_*.py, orchid_*.py — OC pipeline prototypes
  These must NOT be run without review.
  They belong in the Orchid Continuum repo.

TWO DATABASES:
  PGHOST (heliumdb)    → 32 tables  → Calyx operational data
  DATABASE_URL (Neon)  → 302+ tables → Orchid Continuum data platform

ONE HIDDEN TRAP:
  alembic/env.py points to DATABASE_URL (Neon) by default.
  Never run `alembic upgrade` without verifying this.

MOST IMPORTANT FILE:
  replit.md — read this before anything else.
```
