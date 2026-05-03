# BUILD 198 — Schema Alignment Audit
# Orchid Continuum / Calyx Workspace

**Generated:** 2026-05-03
**Method:** Static inspection only. No scripts run. No SQL executed. No database touched.
**Source of truth for Neon schema:** `orchid_continuum_db_audit.txt` (2026-03-14 04:17, 446 table entries across all schemas) and `orchid_continuum_db_audit_current.txt` (2026-03-14 04:32, 113 public tables with row counts).
**Scripts inspected:** 13 root-level Python files, 1 shell script.

---

## Section 1 — Master Table Reference Inventory

Every table name referenced by every root-level script, with full existence verification.

### 1A — Tables Referenced by Write-Capable Scripts

| Table | Script | Operation | Exists in Neon Public? | Status | Notes |
|---|---|---|---|---|---|
| `oc_job_queue` | `oc_automation_worker.py` | SELECT (status='pending'), UPDATE (status='running'/'completed') | **YES** (739 rows) | VALID | Columns used: `id`, `payload`, `priority`, `available_at`, `status`, `finished_at` — all consistent with sample row in audit |
| `oc_harvest_targets` | `oc_automation_worker.py` | SELECT (genus WHERE target_id=?) | **YES** | VALID | Column `genus` unverified — see Section 4 |
| `oc_occurrences` | `oc_automation_worker.py` | INSERT (decimal_latitude, decimal_longitude, source, raw_json) | **YES** (114,517 rows) | VALID — EXISTS but column schema unverified | Columns `decimal_latitude`, `decimal_longitude`, `source`, `raw_json` not confirmed in audit snapshots — see Section 4 |
| `oc_job_queue` | `oc_scheduler.py` | INSERT (job_type, payload, priority, status) | **YES** | VALID | INSERT structure matches confirmed column set |
| `oc_harvest_targets` | `oc_scheduler.py` | SELECT (target_id WHERE state='queued'), UPDATE (state='processing') | **YES** | VALID | Columns `target_id`, `state`, `priority`, `created_at` unverified — see Section 4 |
| `oc_harvest_runs` | `mission_control_scheduler.py` | INSERT (job_type, status, created_at) | **YES** (0 rows) | VALID — EXISTS, 0 rows suggests no runs ever completed | INSERT structure plausible but columns not confirmed |
| `pipeline_runs` | `mission_control_scheduler.py` | INSERT (pipeline_name, status, created_at) | **YES — but in TWO schemas** | AMBIGUOUS | `public.pipeline_runs` confirmed; `oc_mission_control.pipeline_runs` also confirmed. Script default search_path targets `public.pipeline_runs`. See Section 3 — Critical Discovery 1. |
| `oc_worker_registry` | `mission_control_scheduler.py` | SELECT (worker_id, last_seen) | **YES** | VALID | Read-only; columns unverified |
| `oc_occurrences` | `oc_extract_taxonomy.py` | SELECT (occurrence_id, raw_json WHERE species_id IS NULL), UPDATE (species_id, genus_id, country, elevation_m) | **YES** | VALID — EXISTS but column schema unverified | **CRITICAL:** Script executes at module load (top-level code, not in `__main__`). Columns `occurrence_id`, `raw_json`, `species_id`, `genus_id`, `country`, `elevation_m` unverified. Audit shows 37,794 of 114,517 rows have elevation — consistent with `elevation_m` column existing. |

### 1B — Tables Referenced by Read-Only Scripts

| Table | Script | Exists in Neon Public? | Status | Notes |
|---|---|---|---|---|
| `oc_occurrences` | `oc_mission_control.py`, `oc_control_panel.py`, `oc_ingestion_tracker.py`, `orchid_api.py`, `oc_orchid_atlas.py`, `orchid_climate_engine.py`, `api_occurrence_points.py`, `oc_system_health.py` | **YES** | VALID | Most-referenced table. SELECT only in all 8 read-only scripts. |
| `oc_harvest_targets` | `oc_mission_control.py` | **YES** | VALID | `oc_mission_control.py` handles missing table gracefully with try/except |
| `oc_job_queue` | `oc_mission_control.py` | **YES** | VALID | `oc_mission_control.py` handles missing table gracefully |
| `oc_occurrence_records` | `oc_system_check_v2.py` | **NO** | STALE | Not found in any schema audit. See Section 2. |
| `oc_images` | `oc_system_check_v2.py` | **NO** | STALE | Not found in any schema audit. Superseded by `orchid_images`. See Section 2. |
| `oc_taxa` | `oc_system_check_v2.py` | **NO** | STALE | Not in public schema. `taxa` exists in `oc_core` schema. See Section 2 and Critical Discovery 2. |
| `oc_atlas_cells` | `oc_system_check_v2.py` | **NO** | STALE | Not found in any schema audit. Table removed or never migrated. |
| `oc_traits` | `oc_system_check_v2.py` | **NO** | STALE | Not in public schema. Replaced by `traits`, `trait_*` family of tables. See Section 2. |
| `oc_harvesters` | `oc_system_check_v2.py` | **NO** | STALE | Not in public schema. Renamed to `harvesters` (public) and `oc_admin.harvesters`. |
| `oc_harvester_runs` | `oc_system_check_v2.py` | **NO** | STALE | Not in any schema. Closest match: `harvest_logs` (public) or `oc_harvest_runs` (public, 0 rows). |
| `image_assets` | `oc_full_system_audit.sh` | **YES** | VALID | |
| `media_assets` | `oc_full_system_audit.sh` | **YES** | VALID | Confirmed in `orchid_continuum_db_audit.txt` public schema (line 258). |
| `eol_images` | `oc_full_system_audit.sh` | **YES** | VALID | |
| `harvest_jobs` | `oc_full_system_audit.sh`, `app/worker.py` | **YES** | VALID | Also in `neondb_import` schema. `app/worker.py` targets PGHOST (heliumdb), not Neon. |
| `harvest_logs` | `oc_full_system_audit.sh` | **YES** | VALID | |
| `harvest_state` | `oc_full_system_audit.sh` | **YES** | VALID | |
| `gbif_ingest_progress` | `oc_full_system_audit.sh` | **YES** | VALID | |
| `gbif_occurrence_key_refetch_queue` | `oc_full_system_audit.sh` | **YES** | VALID | |
| `agent_tasks` | `oc_full_system_audit.sh` | **YES** | VALID | Also in `neondb_import` schema. |
| `agent_insights` | `oc_full_system_audit.sh` | **YES** | VALID | Also in `neondb_import` schema. |
| `elevation_lookup_log` | `oc_full_system_audit.sh` | **YES** | VALID | |
| `elevation_backfill_queue` | `oc_full_system_audit.sh` | **YES** (492,722 rows) | VALID | |

---

## Section 2 — Stale Table Names

These table names are referenced in root-level scripts but **do not exist** in any known Neon schema as of the 2026-03-14 audit. The schema has evolved; these names belong to an earlier generation of the data model.

| Stale Name | Referenced By | Current Neon Equivalent | Evidence |
|---|---|---|---|
| `oc_occurrence_records` | `oc_system_check_v2.py` | Unclear — possibly `oc_occurrences` (114,517 rows) or `records` (public schema) | `oc_system_check_v2.py` queries `count(*)`, `distinct species`, `distinct genus`, `cell_id`, `elevation_m`. The `oc_occurrences` table exists but has different column names (`species_id` not `species`). |
| `oc_images` | `oc_system_check_v2.py` | `orchid_images` (public, 1,074,218 rows) | `oc_images` not in any schema audit. `orchid_images` is confirmed. Columns used by script (`taxon_id`, `source`, `file_path`, `url`) need to be verified against `orchid_images` actual schema. |
| `oc_taxa` | `oc_system_check_v2.py` | `oc_core.taxa` (different schema) | `oc_taxa` not in public schema. `taxa` confirmed in `oc_core` schema (from `orchid_continuum_db_audit.txt` line 113). Also `oc_taxa_universe` exists in public schema. Script queries `rank`, `accepted_id` columns. |
| `oc_atlas_cells` | `oc_system_check_v2.py` | Unknown — no match in any schema | Atlas grid table not found in 446-table audit. May have been deprecated or never created in current Neon. |
| `oc_traits` | `oc_system_check_v2.py` | `traits` (public) or `trait_*` family | `oc_traits` not found. Current schema has: `traits`, `trait_assertions`, `trait_candidates`, `trait_definitions`, `trait_elevation`, `trait_geography`, `trait_growth_habit`, `trait_observations`, `trait_run_log`, `trait_sources`, `trait_variations`, `traitbank_orchid_traits`. Script queries `count(*)` and `taxon_id`. |
| `oc_harvesters` | `oc_system_check_v2.py` | `harvesters` (public) | `oc_harvesters` not found. `harvesters` confirmed in public (line 231). Also `oc_admin.harvesters` in a separate schema. Script queries `name`, `status` — consistent with `harvesters`. |
| `oc_harvester_runs` | `oc_system_check_v2.py` | `harvest_logs` (public) or `oc_harvest_runs` (public) | Neither exact match. `oc_harvest_runs` has 0 rows. `harvest_logs` is likely the correct replacement. Script queries `harvester_name`, `run_time` — need column verification against `harvest_logs`. |

**Impact:** All 7 stale table names are concentrated in a single script: `oc_system_check_v2.py`. Every query in that script will fail with "table does not exist" errors (the script handles these with `conn.rollback()` per error and continues). The script is non-destructive but completely non-functional against current Neon schema.

---

## Section 3 — Valid Table Names

Tables confirmed to exist in Neon (public schema unless noted) based on the 2026-03-14 audits.

### Write-Capable Script Targets — Confirmed Present

| Table | Row Count (2026-03-14) | Script Reference |
|---|---|---|
| `oc_occurrences` | 114,517 | oc_automation_worker.py (INSERT), oc_extract_taxonomy.py (UPDATE), multiple read-only scripts |
| `oc_job_queue` | 739 | oc_automation_worker.py, oc_scheduler.py, oc_mission_control.py |
| `oc_harvest_targets` | Unknown | oc_automation_worker.py, oc_scheduler.py, oc_mission_control.py |
| `oc_harvest_runs` | 0 | mission_control_scheduler.py |
| `pipeline_runs` | Unknown | mission_control_scheduler.py |
| `oc_worker_registry` | Unknown | mission_control_scheduler.py |

### Read-Only Script Targets — Confirmed Present

| Table | Row Count | Notes |
|---|---|---|
| `image_assets` | Unknown | Confirmed public |
| `media_assets` | Unknown | Confirmed public |
| `eol_images` | Unknown | Confirmed public |
| `harvest_jobs` | 34,563 (heliumdb est.) | Confirmed public; also in neondb_import |
| `harvest_logs` | Unknown | Confirmed public |
| `harvest_state` | Unknown | Confirmed public |
| `gbif_ingest_progress` | Unknown | Confirmed public |
| `gbif_occurrence_key_refetch_queue` | Unknown | Confirmed public |
| `agent_tasks` | Unknown | Confirmed public (also neondb_import) |
| `agent_insights` | Unknown | Confirmed public (also neondb_import) |
| `elevation_lookup_log` | Unknown | Confirmed public |
| `elevation_backfill_queue` | 492,722 | Confirmed public |
| `source_elevation_backfill_queue` | 179,805 | Confirmed public |

### Tables That Appear in Neon But Are Not Referenced by Any Script

These are relevant to the OC pipeline and should be understood before building new pipeline logic.

| Table | Row Count | Significance |
|---|---|---|
| `orchid_images` | 1,074,218 | Main image catalog — supersedes `oc_images` |
| `records` | Unknown | Canonical occurrence/source record layer |
| `record_media_link` | 1,889,737 | Media linkage — see Section 5 |
| `record_taxon_map` | Unknown | Record → taxonomy mapping (FK to oc_core.taxa) |
| `record_traits` | Unknown | Per-record elevation + trait data (has live trigger) |
| `record_inferred_traits` | Unknown | Inferred per-record traits |
| `orchid_occurrence` | Unknown | Parallel to oc_occurrences? Role unclear |
| `orchid_record` | Unknown | Role unclear — may be legacy or curated subset |
| `oc_taxa_universe` | Unknown | May be the current replacement for `oc_taxa` |
| `gbif_occurrence_rehydrate_queue` | 257,227 | Pending GBIF rehydration |
| `gbif_occurrence_rehydrate_queue_v2` | 262,241 | V2 of GBIF rehydration queue |
| `gbif_occurrence_rehydrate_results` | 9,058 | Completed rehydrations |

---

## Section 4 — Unverified Columns (CRITICAL for Script Safety)

The schema audits confirm **table existence** but do not provide **column-level schemas** for most tables. The following column assumptions in root-level scripts are unverified and must be confirmed by Julius (or a fresh `\d tablename` query) before any write script is run.

### `oc_occurrences` — Most Urgently Needed

| Column | Referenced By | Confidence |
|---|---|---|
| `occurrence_id` | `oc_extract_taxonomy.py` (WHERE clause) | MEDIUM — consistent with GBIF-style naming |
| `decimal_latitude` | `oc_automation_worker.py` (INSERT), multiple read-only | HIGH — confirmed as column via `orchid_climate_engine.py` SELECT which works (atlas CSV generated) |
| `decimal_longitude` | `oc_automation_worker.py` (INSERT), multiple read-only | HIGH — same evidence |
| `source` | `oc_automation_worker.py` (INSERT) | MEDIUM — plausible but unverified |
| `raw_json` | `oc_automation_worker.py` (INSERT), `oc_extract_taxonomy.py` (SELECT) | MEDIUM — GBIF JSON storage pattern |
| `species_id` | `oc_extract_taxonomy.py` (SELECT WHERE NULL, UPDATE), `oc_control_panel.py` (SELECT DISTINCT) | MEDIUM — consistent with the audit elevation stats (37,794 of 114,517 have elevation, implies partial population) |
| `genus_id` | `oc_extract_taxonomy.py` (UPDATE), `oc_control_panel.py` (SELECT DISTINCT) | MEDIUM |
| `genus` | `orchid_climate_engine.py` (SELECT), `oc_mission_control.py` (SELECT) | MEDIUM — possible `genus` string column alongside `genus_id` integer FK |
| `country` | `oc_extract_taxonomy.py` (UPDATE), `oc_control_panel.py` (SELECT DISTINCT) | MEDIUM |
| `elevation_m` | `oc_extract_taxonomy.py` (UPDATE), `oc_control_panel.py` (SELECT min/max/avg) | HIGH — the audit reports `with_elevation: 37794 / missing: 76723` which directly implies this column exists |

**Risk assessment:** `oc_occurrences` column schema is partially confirmed by inference. The presence of `elevation_m` is effectively confirmed by the audit row count stats. The INSERT columns (`decimal_latitude`, `decimal_longitude`, `source`, `raw_json`) are high-confidence. The UPDATE columns in `oc_extract_taxonomy.py` are medium-confidence. The script is still unsafe to run because it executes at module load time (top-level code, not guarded by `if __name__ == '__main__'`).

### `oc_harvest_targets` — Second Priority

| Column | Referenced By | Confidence |
|---|---|---|
| `target_id` | `oc_automation_worker.py`, `oc_scheduler.py` | MEDIUM |
| `state` | `oc_scheduler.py` (WHERE state='queued', UPDATE state='processing') | MEDIUM |
| `genus` | `oc_automation_worker.py` (SELECT genus WHERE target_id=?) | LOW — naming convention suggests a genus per target, but could be different column name |
| `priority` | `oc_scheduler.py` (ORDER BY priority DESC) | MEDIUM |
| `created_at` | `oc_scheduler.py` (ORDER BY created_at) | HIGH — standard column |

### `oc_harvest_runs` — Third Priority

| Column | Referenced By | Confidence |
|---|---|---|
| `job_type` | `mission_control_scheduler.py` (INSERT) | MEDIUM |
| `status` | `mission_control_scheduler.py` (INSERT 'pending') | MEDIUM |
| `created_at` | `mission_control_scheduler.py` (INSERT now()) | HIGH |
| `id` | `mission_control_scheduler.py` (RETURNING id) | HIGH — standard PK |

---

## Section 5 — What Is `record_media_link`?

This is the most significant undocumented table in the workspace. Based on static analysis only.

**What is known:**
- Table name: `record_media_link`
- Schema: `public`
- Row count: **1,889,737** (as of 2026-03-14, from `orchid_continuum_db_audit_current.txt`)
- This is more rows than `orchid_images` (1,074,218), meaning on average each record links to ~1.8 media items, or some records link to multiple media items
- Table exists alongside: `records`, `record_taxon_map`, `record_traits`, `record_inferred_traits`

**Inferred purpose (from naming conventions and schema context):**

The `record_*` table family appears to implement a **canonical record layer** sitting between raw source data and the image/taxonomy catalogs:

```
Source APIs (GBIF, EOL, iDigBio, CalPhotos, Wikimedia)
    ↓
records                 ← canonical deduplicated occurrence/specimen records
    ↓                           ↓                       ↓
record_media_link       record_taxon_map        record_traits
(1,889,737 rows)        (link to taxa)          (elevation + trigger)
(links to images)           ↓                       
                        oc_core.taxa             
                        (taxonomy authority)
```

`record_media_link` likely contains:
- `record_id` — FK to `records`
- `media_id` or `image_id` — FK to `orchid_images`, `image_assets`, or a URL
- `source` — which API the media came from
- Link metadata (confidence, scraped_at, status, etc.)

**Why this matters for pipeline design:**
- `orchid_images` stores the **image metadata and download status** (1,074,218 rows)
- `record_media_link` stores the **source → canonical record linkage** (1,889,737 rows)
- These are complementary, not duplicates
- Any elevation backfill should target `record_traits.elev_m` (has a normalization trigger) rather than `orchid_images.elevation_meters` — or possibly both depending on what each table's role is confirmed to be
- No root-level script currently reads or writes `record_media_link` — it is an undocumented but heavily-populated table

**What Julius needs to determine:**
- The column schema of `record_media_link` (`\d record_media_link`)
- The column schema of `records` (`\d records`)
- Whether `record_media_link.image_id` FKs to `orchid_images.id`
- Whether `records` overlaps with or is a superset of `oc_occurrences`
- Row count and schema of `orchid_record` (may be the same concept under a different name)

---

## Section 6 — Critical Discoveries

### Discovery 1: `pipeline_runs` Exists in Two Schemas

`mission_control_scheduler.py` does:
```python
INSERT INTO pipeline_runs (pipeline_name, status, created_at) VALUES (%s,'pending',now())
```

Two tables match this name:
- `public.pipeline_runs` — confirmed in both audits
- `oc_mission_control.pipeline_runs` — confirmed in `orchid_continuum_db_audit.txt` (line 125)

Without an explicit schema prefix, a psycopg2 connection using default search_path will INSERT into `public.pipeline_runs`. This may or may not be the intended target. If the OC Mission Control system reads from `oc_mission_control.pipeline_runs`, the script is writing to the wrong table.

**Implication:** `mission_control_scheduler.py` should not be run until the intended `pipeline_runs` target is confirmed.

---

### Discovery 2: `oc_taxa` Is Gone From Public — `taxa` Lives in `oc_core`

`oc_system_check_v2.py` queries `oc_taxa` with:
```sql
SELECT count(*) FROM oc_taxa WHERE rank='species';
SELECT count(*) FROM oc_taxa WHERE rank='genus';
```

`oc_taxa` does not exist in the public schema. However:
- `taxa` exists in the `oc_core` schema (`oc_core.taxa`) — confirmed in `orchid_continuum_db_audit.txt` (line 113)
- `oc_taxa_universe` exists in public schema (unknown row count)

The `record_taxon_map` table FK references `taxa(taxon_id)` — given `taxa` is in `oc_core`, the FK is `oc_core.taxa(taxon_id)`. This means the default search_path must include `oc_core` for FK resolution to work, implying that the Neon database has `oc_core` in its default search_path (or the FK is cross-schema, which PostgreSQL supports).

**Implication:** Any query or script referencing `oc_taxa` will fail. The replacement is either `oc_core.taxa` (with schema prefix) or `oc_taxa_universe` (public). `oc_system_check_v2.py` needs to be rewritten before it can work as a health check.

---

### Discovery 3: `oc_extract_taxonomy.py` Executes at Import Time

```python
# oc_extract_taxonomy.py — top-level code, NOT in __main__:
conn = psycopg2.connect(DB)
cur = conn.cursor()
cur.execute("SELECT occurrence_id, raw_json FROM oc_occurrences WHERE species_id IS NULL LIMIT 5000")
rows = cur.fetchall()
...
for species, genus, country, elevation, occ_id in updates:
    cur.execute("UPDATE oc_occurrences SET species_id=..., genus_id=..., country=..., elevation_m=... WHERE occurrence_id=...")
conn.commit()
```

This code runs the moment the file is loaded by Python — whether via `python oc_extract_taxonomy.py` or via `import` from `oc_extract_all.py`. There is no `if __name__ == '__main__'` guard. 

**oc_extract_all.py** calls it via subprocess: `subprocess.run(["python", "oc_extract_taxonomy.py"])` — 30 times. Each subprocess invocation triggers a fresh connect + SELECT 5000 + batch UPDATE + commit cycle.

**Implication:** This script cannot be "just inspected" by importing. Any invocation by any means triggers the write path against Neon production.

---

### Discovery 4: Neon Has 13 Named Schemas (Not Just `public`)

The March 2026 audit reveals Neon's full schema layout:

| Schema | Tables | Purpose |
|---|---|---|
| `public` | 200+ | Main OC data: occurrences, images, taxonomy, traits, harvesting, pipelines, user features |
| `governance` | 4 | communication, repo, work_item, work_item_dep |
| `kg` | 4 | knowledge graph: entities, literals, relationships, build runs |
| `neondb_import` | ~30 | Parallel copies of some public tables plus import-stage tables |
| `oc_admin` | 14 | harvesters, audit_runs, modules, tasks, tools, deployments |
| `oc_core` | 3 | **name_xref, source_snapshots, taxa** — the canonical taxonomy authority |
| `oc_governance` | 3 | constitution_documents, governance_rules, operating_policies |
| `oc_graph` | 7 | Knowledge graph: edges, nodes, quality metrics |
| `oc_mission_control` | 4 | **pipeline_runs** (the real one?), queue_metrics, system_tracker, worker_heartbeat |
| `oc_norm` | 2 | country_alias, trait_geography_norm |
| `oc_source` | 4 | source snapshots, world_plants data |
| `oc_staging` | 4 | Taxonomy reconciliation staging |
| `oc_watchdog` | 1 | data_integrity_audit |
| `tax_stab` | 5 | Taxonomy stability: name_strings, record_name_assertions, record_taxon_mappings, synonym_assertions, taxonomy_conflicts |
| `taxonomy_identity` | 4 | canonical_taxon, implied_taxon, powo_snapshot, powo_stage_raw |

**Implication:** Scripts connecting to Neon with default search_path only see `public` schema tables. References to `oc_core.taxa`, `oc_mission_control.pipeline_runs`, `oc_admin.harvesters`, etc. require explicit schema prefixes. No root-level script uses explicit schema prefixes — they all assume `public` only.

---

### Discovery 5: Two Elevation Queues with 672,527 Combined Pending Rows

| Queue | Rows (2026-03-14) |
|---|---|
| `elevation_backfill_queue` | 492,722 |
| `source_elevation_backfill_queue` | 179,805 |
| **Total** | **672,527** |

Neither queue is referenced by any root-level script. No elevation backfill worker exists in this workspace. These queues are already populated — someone or some process created them — but the worker to drain them does not exist here.

Additionally, `record_traits` (which stores the results) has an active PostgreSQL trigger `trg_normalize_elevation` that fires on INSERT/UPDATE of elevation columns. The backfill infrastructure is more complete than previously known.

---

## Section 7 — Scripts Blocked from Execution Until Schema Alignment

Scripts that should not be run until column-level schema verification is completed or fixed.

### BLOCKED — Stale schema, all queries will fail

| Script | Reason | Fix Required |
|---|---|---|
| `oc_system_check_v2.py` | 7 of 7 table references are stale (`oc_occurrence_records`, `oc_images`, `oc_taxa`, `oc_atlas_cells`, `oc_traits`, `oc_harvesters`, `oc_harvester_runs`) | Rewrite every query with current table names; cannot be fixed without Julius confirming column schemas of replacement tables |

### BLOCKED — Write operations, column schema unverified

| Script | Reason | Fix Required |
|---|---|---|
| `oc_extract_taxonomy.py` | Bulk UPDATE `oc_occurrences` — column schema partially inferred but not confirmed. Also executes at import time with no guard. | Confirm `oc_occurrences` column schema via `\d oc_occurrences`. Add `if __name__ == '__main__'` guard. Review whether `occurrence_id` PK matches the actual column name. |
| `oc_extract_all.py` | Runs `oc_extract_taxonomy.py` 30 times | Blocked until `oc_extract_taxonomy.py` is resolved |
| `oc_automation_worker.py` | INSERT into `oc_occurrences`, SELECT `oc_harvest_targets.genus` — column schema unverified | Confirm `oc_occurrences` column schema. Confirm `oc_harvest_targets` column schema. Confirm `state` column values ('queued'/'processing'). |
| `oc_scheduler.py` | UPDATE `oc_harvest_targets.state` — column schema unverified | Confirm `oc_harvest_targets` schema: `target_id`, `state`, `priority`, `created_at`. |
| `mission_control_scheduler.py` | INSERT into `pipeline_runs` — ambiguous target schema (public vs oc_mission_control). INSERT into `oc_harvest_runs` — column schema unverified. Infinite loop. | Confirm which `pipeline_runs` is the intended target. Confirm `oc_harvest_runs` schema. |

### CONDITIONALLY SAFE — Read-only, but stale schema will cause errors

| Script | Condition | Notes |
|---|---|---|
| `oc_system_check_v2.py` | NOT SAFE — all queries fail | Each query wraps in try/except + rollback, so it won't crash, but zero results are meaningful |
| `oc_mission_control.py` | CONDITIONALLY SAFE — has per-query try/except | Tables exist; columns (`genus`, `state`) unverified; will degrade gracefully if columns missing |
| `oc_control_panel.py` | CONDITIONALLY SAFE | `oc_occurrences` exists; columns (`species_id`, `genus_id`, `country`, `elevation_m`) medium-confidence |

### SAFE — Confirmed tables, read-only

| Script | Status |
|---|---|
| `oc_full_system_audit.sh` | SAFE — all queried tables confirmed present; each wrapped with `|| echo "missing"` |
| `orchid_api.py` | SAFE if not activated via uvicorn; read-only against `oc_occurrences` |
| `api_occurrence_points.py` | SAFE if not activated; read-only against `oc_occurrences` |
| `oc_system_health.py` | SAFE if not activated; read-only COUNT against `oc_occurrences` |
| `oc_orchid_atlas.py` | SAFE if `folium` is installed; read-only SELECT from `oc_occurrences`, writes HTML only |
| `orchid_climate_engine.py` | SAFE; read-only SELECT from `oc_occurrences`, writes CSV only |
| `oc_ingestion_tracker.py` | SAFE; single COUNT query against `oc_occurrences`. Note: connects at import time. |
| `oc_repo_inventory.sh` | SAFE; no DB connection |

---

## Section 8 — Summary Tables

### Stale Table Names (6)

| Stale Name | Current Replacement | Where |
|---|---|---|
| `oc_occurrence_records` | Possibly `oc_occurrences` or `records` | Public schema |
| `oc_images` | `orchid_images` | Public schema |
| `oc_taxa` | `oc_core.taxa` | oc_core schema (requires schema prefix) |
| `oc_atlas_cells` | Unknown / may not exist | Not found |
| `oc_traits` | `traits`, `trait_*` family | Public schema |
| `oc_harvesters` | `harvesters` (public) or `oc_admin.harvesters` | Multi-schema |
| `oc_harvester_runs` | `harvest_logs` (public) or `oc_harvest_runs` (public) | Public schema |

### Valid Table Names — Confirmed in Neon (subset relevant to scripts)

`oc_occurrences`, `oc_job_queue`, `oc_harvest_targets`, `oc_harvest_runs`, `pipeline_runs`, `oc_worker_registry`, `orchid_images`, `image_assets`, `media_assets`, `eol_images`, `harvest_jobs`, `harvest_logs`, `harvest_state`, `gbif_ingest_progress`, `gbif_occurrence_key_refetch_queue`, `agent_tasks`, `agent_insights`, `elevation_lookup_log`, `elevation_backfill_queue`, `source_elevation_backfill_queue`, `harvesters`, `traits`, `records`, `record_media_link`, `record_taxon_map`, `record_traits`

### Unknown Tables — Need Julius Review

| Table | Why Unknown | Priority |
|---|---|---|
| `record_media_link` | 1.89M rows, no column schema, no script references it yet, central to pipeline design | **HIGH** |
| `records` | Canonical record layer — may be the source of truth for both `oc_occurrences` and `orchid_images` | **HIGH** |
| `oc_taxa_universe` | Possible replacement for `oc_taxa`, column schema unknown | HIGH |
| `orchid_occurrence` | Parallel to `oc_occurrences`? Relationship unclear | MEDIUM |
| `orchid_record` | Relationship to `records` and `orchid_images` unclear | MEDIUM |
| `oc_core.taxa` | Referenced by `record_taxon_map` FK — is this the canonical taxonomy PK? | HIGH |
| `taxonomy_identity.*` | 4 tables including `canonical_taxon`, `powo_snapshot` — taxonomy identity authority layer | MEDIUM |
| `elevation_backfill_queue` | 492K rows, no worker, no column schema — critical for elevation pipeline design | HIGH |
| `source_elevation_backfill_queue` | 179K rows, relationship to main queue unclear | MEDIUM |

### Scripts Blocked from Future Execution (5)

| Script | Block Reason |
|---|---|
| `oc_system_check_v2.py` | All 7 table names stale — script is non-functional against current schema |
| `oc_extract_taxonomy.py` | Column schema unverified; executes at import time; writes to Neon production |
| `oc_extract_all.py` | Blocked by `oc_extract_taxonomy.py` dependency |
| `oc_automation_worker.py` | `oc_occurrences` INSERT columns and `oc_harvest_targets` schema unverified |
| `mission_control_scheduler.py` | Ambiguous `pipeline_runs` target (public vs oc_mission_control schema); infinite loop |

`oc_scheduler.py` is **conditionally blocked** — table exists but column schema (`target_id`, `state`, `priority`) unverified before the UPDATE path is considered safe.

---

## Section 9 — Recommended Next Build

**Build 199 — Julius: Column-Level Schema Verification**

Ask Julius to run the following against Neon (read-only `\d` queries, no writes):

```sql
\d oc_occurrences
\d oc_harvest_targets
\d oc_harvest_runs
\d oc_job_queue
\d records
\d record_media_link
\d record_taxon_map
\d orchid_images
\d elevation_backfill_queue
\d source_elevation_backfill_queue
\d oc_taxa_universe
SELECT COUNT(*) FROM oc_core.taxa;
\d oc_core.taxa
\d oc_mission_control.pipeline_runs
\d public.pipeline_runs
```

**Deliverable:** A column-schema reference document (`build_199_column_schemas.md`) that maps every column in these 14 tables. This is the prerequisite gating every blocked script and every pipeline build in the OC repo.

**Why Julius and not Replit Agent?** The column schema queries against Neon require direct psql access with the correct DATABASE_URL credential and the ability to set `search_path` to include non-public schemas. Julius has persistent Neon access; Replit Agent should not open live SQL sessions against production Neon.

**Alternative next build (if Julius is not available):**

**Build 199B — Calyx: `alembic/env.py` Safety Comment**

Replit Agent adds a prominent comment to `alembic/env.py` warning that it targets `DATABASE_URL` (Neon) by default. Two-minute change. Zero risk. Eliminates the silent trap documented in Build 197.
