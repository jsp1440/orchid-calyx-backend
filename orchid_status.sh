#!/usr/bin/env bash
set -u

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL is not set"
  exit 1
fi

TMP_OUT="$(mktemp)"

run_query() {
  local label="$1"
  local sql="$2"

  echo "==================================================" >> "$TMP_OUT"
  echo "$label" >> "$TMP_OUT"
  echo "==================================================" >> "$TMP_OUT"

  psql "$DATABASE_URL" -v ON_ERROR_STOP=0 -P pager=off -t -A -F ' | ' -c "$sql" >> "$TMP_OUT" 2>&1
  echo "" >> "$TMP_OUT"
}

echo "ORCHID CONTINUUM STATUS"
echo "Generated: $(date)"
echo ""

run_query "CORE TABLE PRESENCE" "
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'taxa',
    'records',
    'image_assets',
    'media_assets',
    'harvest_jobs',
    'harvest_logs',
    'harvest_state',
    'harvesters',
    'gbif_ingest_progress',
    'eol_ingest_progress',
    'eol_images',
    'dem_backfill_queue',
    'elevation_lookup_log',
    'traits',
    'record_traits',
    'record_taxon_map',
    'taxonomy_resolution',
    'taxonomy_species',
    'taxonomy_genus',
    'oc_harvester_registry',
    'oc_harvest_runs',
    'agent_tasks',
    'agent_insights',
    'agent_commands',
    'ai_task_metrics'
  )
ORDER BY table_name;
"

run_query "TOTAL TABLE COUNT" "
SELECT COUNT(*) AS total_public_tables
FROM information_schema.tables
WHERE table_schema = 'public';
"

run_query "TAXONOMY STATUS" "
SELECT 'taxa' AS table_name, COUNT(*) AS row_count FROM taxa
UNION ALL
SELECT 'taxonomy_species', COUNT(*) FROM taxonomy_species
UNION ALL
SELECT 'taxonomy_genus', COUNT(*) FROM taxonomy_genus
UNION ALL
SELECT 'taxonomy_resolution', COUNT(*) FROM taxonomy_resolution
UNION ALL
SELECT 'taxonomy_authority_claims', COUNT(*) FROM taxonomy_authority_claims
UNION ALL
SELECT 'unresolved_taxonomy_names', COUNT(*) FROM unresolved_taxonomy_names;
"

run_query "RECORD STATUS" "
SELECT 'records' AS table_name, COUNT(*) AS row_count FROM records
UNION ALL
SELECT 'record_taxon_map', COUNT(*) FROM record_taxon_map
UNION ALL
SELECT 'record_traits', COUNT(*) FROM record_traits
UNION ALL
SELECT 'orchid_record', COUNT(*) FROM orchid_record
UNION ALL
SELECT 'orchid_occurrence', COUNT(*) FROM orchid_occurrence;
"

run_query "IMAGE STATUS" "
SELECT 'image_assets' AS table_name, COUNT(*) AS row_count FROM image_assets
UNION ALL
SELECT 'media_assets', COUNT(*) FROM media_assets
UNION ALL
SELECT 'eol_images', COUNT(*) FROM eol_images
UNION ALL
SELECT 'eol_images_raw', COUNT(*) FROM eol_images_raw
UNION ALL
SELECT 'orchid_images', COUNT(*) FROM orchid_images
UNION ALL
SELECT 'oc_eol_orchid_images', COUNT(*) FROM oc_eol_orchid_images
UNION ALL
SELECT 'oc_gbif_orchid_images', COUNT(*) FROM oc_gbif_orchid_images;
"

run_query "IMAGE LINKING STATUS" "
SELECT 'record_media_link' AS table_name, COUNT(*) AS row_count FROM record_media_link
UNION ALL
SELECT 'backup_orchid_images_record_link_fix', COUNT(*) FROM backup_orchid_images_record_link_fix
UNION ALL
SELECT 'backup_orchid_images_unlinked_taxonomy_fix', COUNT(*) FROM backup_orchid_images_unlinked_taxonomy_fix;
"

run_query "HARVEST SYSTEM STATUS" "
SELECT 'harvest_jobs' AS table_name, COUNT(*) AS row_count FROM harvest_jobs
UNION ALL
SELECT 'harvest_logs', COUNT(*) FROM harvest_logs
UNION ALL
SELECT 'harvest_state', COUNT(*) FROM harvest_state
UNION ALL
SELECT 'harvesters', COUNT(*) FROM harvesters
UNION ALL
SELECT 'oc_harvester_registry', COUNT(*) FROM oc_harvester_registry
UNION ALL
SELECT 'oc_harvest_runs', COUNT(*) FROM oc_harvest_runs
UNION ALL
SELECT 'oc_harvest_commands', COUNT(*) FROM oc_harvest_commands
UNION ALL
SELECT 'oc_harvest_targets', COUNT(*) FROM oc_harvest_targets
UNION ALL
SELECT 'oc_harvester_heartbeat', COUNT(*) FROM oc_harvester_heartbeat;
"

run_query "GBIF / EOL INGEST STATUS" "
SELECT 'gbif_ingest_progress' AS table_name, COUNT(*) AS row_count FROM gbif_ingest_progress
UNION ALL
SELECT 'gbif_download_progress', COUNT(*) FROM gbif_download_progress
UNION ALL
SELECT 'gbif_occurrence_key_refetch_queue', COUNT(*) FROM gbif_occurrence_key_refetch_queue
UNION ALL
SELECT 'gbif_occurrence_rehydrate_queue', COUNT(*) FROM gbif_occurrence_rehydrate_queue
UNION ALL
SELECT 'gbif_occurrence_rehydrate_queue_v2', COUNT(*) FROM gbif_occurrence_rehydrate_queue_v2
UNION ALL
SELECT 'gbif_occurrence_rehydrate_results', COUNT(*) FROM gbif_occurrence_rehydrate_results
UNION ALL
SELECT 'eol_ingest_progress', COUNT(*) FROM eol_ingest_progress;
"

run_query "ELEVATION STATUS" "
SELECT 'elevation_lookup_log' AS table_name, COUNT(*) AS row_count FROM elevation_lookup_log
UNION ALL
SELECT 'elevation_backfill_queue', COUNT(*) FROM elevation_backfill_queue
UNION ALL
SELECT 'dem_backfill_queue', COUNT(*) FROM dem_backfill_queue
UNION ALL
SELECT 'species_elevation_profile', COUNT(*) FROM species_elevation_profile
UNION ALL
SELECT 'taxon_elevation_profile', COUNT(*) FROM taxon_elevation_profile;
"

run_query "TRAIT STATUS" "
SELECT 'traits' AS table_name, COUNT(*) AS row_count FROM traits
UNION ALL
SELECT 'traitbank_orchid_traits', COUNT(*) FROM traitbank_orchid_traits
UNION ALL
SELECT 'orchid_traits', COUNT(*) FROM orchid_traits
UNION ALL
SELECT 'record_inferred_traits', COUNT(*) FROM record_inferred_traits
UNION ALL
SELECT 'fused_traits', COUNT(*) FROM fused_traits
UNION ALL
SELECT 'trait_observations', COUNT(*) FROM trait_observations
UNION ALL
SELECT 'trait_sources', COUNT(*) FROM trait_sources
UNION ALL
SELECT 'trait_run_log', COUNT(*) FROM trait_run_log;
"

run_query "AUTOMATION / AGENT STATUS" "
SELECT 'agent_tasks' AS table_name, COUNT(*) AS row_count FROM agent_tasks
UNION ALL
SELECT 'agent_insights', COUNT(*) FROM agent_insights
UNION ALL
SELECT 'agent_commands', COUNT(*) FROM agent_commands
UNION ALL
SELECT 'ai_task_metrics', COUNT(*) FROM ai_task_metrics
UNION ALL
SELECT 'ai_sessions', COUNT(*) FROM ai_sessions
UNION ALL
SELECT 'ai_cache', COUNT(*) FROM ai_cache;
"

run_query "RECENT HARVEST / JOB ACTIVITY" "
SELECT 'harvest_logs latest' AS section, *
FROM (
  SELECT id, created_at, level, message
  FROM harvest_logs
  ORDER BY created_at DESC
  LIMIT 10
) x;
"

run_query "RECENT AGENT ACTIVITY" "
SELECT 'agent_tasks latest' AS section, *
FROM (
  SELECT *
  FROM agent_tasks
  ORDER BY created_at DESC
  LIMIT 10
) x;
"

run_query "RECENT ELEVATION ACTIVITY" "
SELECT 'elevation_lookup_log latest' AS section, *
FROM (
  SELECT *
  FROM elevation_lookup_log
  ORDER BY created_at DESC
  LIMIT 10
) x;
"

run_query "RECENT INGEST ACTIVITY" "
SELECT 'gbif_ingest_progress latest' AS section, *
FROM (
  SELECT *
  FROM gbif_ingest_progress
  ORDER BY created_at DESC
  LIMIT 10
) x;
"

cat "$TMP_OUT"
rm -f "$TMP_OUT"