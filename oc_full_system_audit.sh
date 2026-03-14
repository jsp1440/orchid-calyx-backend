#!/bin/bash

echo "======================================="
echo "ORCHID CONTINUUM FULL SYSTEM AUDIT"
echo "======================================="
echo ""

if [ -z "$DATABASE_URL" ]; then
  echo "ERROR: DATABASE_URL not set"
  exit 1
fi

run_query () {
  psql "$DATABASE_URL" -t -A -c "$1"
}

echo ""
echo "---- DATABASE TABLE COUNT ----"
run_query "
SELECT COUNT(*)
FROM information_schema.tables
WHERE table_schema='public';
"

echo ""
echo "---- TABLE LIST (first 50) ----"
run_query "
SELECT table_name
FROM information_schema.tables
WHERE table_schema='public'
ORDER BY table_name
LIMIT 50;
"

echo ""
echo "---- IMAGE TABLE STATUS ----"

echo "image_assets:"
run_query "SELECT COUNT(*) FROM image_assets;" 2>/dev/null || echo "missing"

echo "media_assets:"
run_query "SELECT COUNT(*) FROM media_assets;" 2>/dev/null || echo "missing"

echo "eol_images:"
run_query "SELECT COUNT(*) FROM eol_images;" 2>/dev/null || echo "missing"

echo ""
echo "---- HARVESTER STATUS ----"

echo "harvest_jobs:"
run_query "SELECT COUNT(*) FROM harvest_jobs;" 2>/dev/null || echo "missing"

echo "harvest_logs:"
run_query "SELECT COUNT(*) FROM harvest_logs;" 2>/dev/null || echo "missing"

echo "harvest_state:"
run_query "SELECT COUNT(*) FROM harvest_state;" 2>/dev/null || echo "missing"

echo ""
echo "---- GBIF INGEST ----"

echo "gbif_ingest_progress:"
run_query "SELECT COUNT(*) FROM gbif_ingest_progress;" 2>/dev/null || echo "missing"

echo "gbif_occurrence_refetch:"
run_query "SELECT COUNT(*) FROM gbif_occurrence_key_refetch_queue;" 2>/dev/null || echo "missing"

echo ""
echo "---- AUTOMATION SYSTEM ----"

echo "agent_tasks:"
run_query "SELECT COUNT(*) FROM agent_tasks;" 2>/dev/null || echo "missing"

echo "agent_insights:"
run_query "SELECT COUNT(*) FROM agent_insights;" 2>/dev/null || echo "missing"

echo ""
echo "---- ELEVATION DATA ----"

echo "elevation_lookup_log:"
run_query "SELECT COUNT(*) FROM elevation_lookup_log;" 2>/dev/null || echo "missing"

echo "elevation_backfill_queue:"
run_query "SELECT COUNT(*) FROM elevation_backfill_queue;" 2>/dev/null || echo "missing"

echo ""
echo "---- IMAGE QUALITY ----"

echo "duplicate images:"
run_query "
SELECT COUNT(*)
FROM (
SELECT hash, COUNT(*)
FROM image_assets
GROUP BY hash
HAVING COUNT(*) > 1
) dup;
" 2>/dev/null || echo "unable to check"

echo ""
echo "======================================="
echo "AUDIT COMPLETE"
echo "======================================="