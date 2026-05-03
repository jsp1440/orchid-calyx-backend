# BUILD 196A — Start Here
# Orchid Continuum / Calyx Workspace — One-Page Orientation

**Generated:** 2026-05-03
**For:** Jeff, advisors, grant reviewers, future developers, Replit Agent

---

## What is this workspace?

This Replit project hosts **Calyx**, a production-ready backend API for orchid show management (shows, entries, judging, volunteers, awards). It is built in Python/FastAPI and connects to two PostgreSQL databases:

- **PGHOST (heliumdb)** — Replit-hosted. Calyx operational data: shows, judges, scorecards, volunteers.
- **DATABASE_URL (Neon)** — Orchid Continuum platform. 302 tables. 1M+ orchid images, real AOS judging criteria, GBIF occurrence queues.

The root directory also contains **prototype scripts** from earlier Orchid Continuum work (harvesters, climate engine, atlas generator). These are **not active** and should not be run without careful review.

---

## What should NOT be touched?

| Do Not Touch | Why |
|---|---|
| `oc_extract_all.py` | Runs 30 batches of 5,000-row UPDATEs against Neon production |
| `oc_extract_taxonomy.py` | Bulk UPDATE of `oc_occurrences` — stale schema, could corrupt |
| `mission_control_scheduler.py` | Infinite hourly loop that INSERTs into Neon tables |
| `oc_scheduler.py` | Infinite loop, updates `oc_harvest_targets` on Neon |
| `oc_automation_worker.py` | Bulk INSERTs into `oc_occurrences` on Neon |
| `.env` / environment variables | Live database credentials — Neon and heliumdb both active |
| `orchid_dump.dump` | Empty — not a real backup, do not treat as one |
| `orchid_schema.sql` | Empty — not a real schema export |
| `DATABASE_URL` | Points to Neon production — 302 tables, 1M+ rows of real data |

**Rule of thumb:** If a root-level file contains `DATABASE_URL` and loops, do not run it.

---

## What should be read first?

1. **`replit.md`** — The authoritative project memory. Full model list, all API endpoints, environment variable reference, design philosophy, schema management approach.
2. **`docs/preservation/build_196A_current_state_preservation_index.md`** — Full workspace map, write-risk analysis, preservation risks.
3. **`app/main.py`** — FastAPI entry point. Shows startup sequence, schema reconciliation, all registered routers.
4. **`app/models.py`** — All 32 SQLAlchemy models for the Calyx heliumdb database.
5. **`README.md`** — Public-facing API overview (note: partially outdated, does not cover judging system or volunteer ops).

---

## What is safe to ask Replit Agent to do?

**Safe:**
- Add, modify, or fix endpoints in `app/routers/`
- Update `app/models.py` or `app/schemas.py`
- Update `replit.md` or `README.md`
- Run the Calyx API server (`uvicorn app.main:app`)
- Query heliumdb (PGHOST) for Calyx operational data
- Read-only queries against Neon (DATABASE_URL) for inspection
- Create documentation files in `docs/`
- Generate `seed.sql` demo data for Calyx
- Run `tools/introspect_api.py` to inspect routes

**Requires explicit approval first:**
- Modifying any root-level `oc_*.py` or `orchid_*.py` scripts
- Running any script that loops against DATABASE_URL
- Touching `alembic/` or attempting Alembic migrations
- Dropping or renaming tables in either database
- Adding new workflows to `.replit`

**Do not ask Replit Agent to:**
- Activate the harvester engine, scrapers, or elevation backfill in this repo (belongs in Orchid Continuum repo)
- Run `oc_extract_all.py` or `oc_automation_worker.py`
- Commit or push without explicit instruction

---

## What should be reserved for Julius, Colab, or manual review?

| Task | Where |
|---|---|
| Elevation backfill for 1M+ `orchid_images` rows | Julius / Colab (large batch job) |
| GBIF occurrence rehydration (257K queue) | Julius / Colab / dedicated worker |
| Image download pipeline (1M pending) | Dedicated worker process, Orchid Continuum repo |
| Schema analysis of all 302 Neon tables | Julius SQL analysis |
| Taxonomy identity layer design | Julius / manual review |
| Perceptual hash deduplication of images | Julius / Colab |
| Climate envelope modeling beyond lat/lon approximation | Julius / Colab with actual WorldClim data |
| GBIF_NON_ORCHID purge (366K rows flagged) | Manual audit before any deletion |
| Calyx → Neon read-only adapter endpoints | Replit Agent (small, safe) |

---

## Two-sentence summary for grant reviewers

Calyx is a live API powering orchid show management (judging, volunteers, entries) for orchid societies, backed by real AOS scoring criteria. It sits alongside the Orchid Continuum data platform, which has catalogued over 1 million orchid images from GBIF, iNaturalist, iDigBio, and EOL — with taxonomy, occurrence geography, and media pipelines under active development.

---

## Key numbers (as of 2026-05-03)

| Metric | Value |
|---|---|
| Calyx API tables (heliumdb) | 32 |
| Orchid Continuum tables (Neon) | 302 |
| Orchid images catalogued | 1,096,958 |
| Images downloaded | 6,842 (EOL only) |
| Images with elevation | 1,036 (0.09%) |
| GBIF occurrence rehydration queue | 257,227 pending |
| AOS judging criteria (live) | 58 |
| AOS judging awards (live) | 36 |
| Harvesters registered | 9 (all in error or disabled) |
| Harvest jobs completed | 34,563 |
