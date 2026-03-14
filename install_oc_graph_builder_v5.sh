#!/usr/bin/env bash
set -euo pipefail

echo
echo "Installing Orchid Continuum Graph Builder v5..."
echo

psql "$DATABASE_URL" <<'SQL'

DROP FUNCTION IF EXISTS oc_graph.build_graph_from_normalized();

CREATE OR REPLACE FUNCTION oc_graph.build_graph_from_normalized()
RETURNS TEXT
LANGUAGE plpgsql
AS $$
DECLARE
    v_run_id BIGINT;
BEGIN

INSERT INTO oc_graph.kg_build_runs
(build_name,status,started_at)
VALUES
('normalized_graph_build','running',now())
RETURNING build_run_id INTO v_run_id;

-------------------------------------------------
-- TAXON NODES
-------------------------------------------------

INSERT INTO oc_graph.kg_nodes
(
node_type,
canonical_key,
display_label,
source_table,
source_pk,
payload_json,
is_active,
build_run_id,
created_at
)
SELECT
'taxon',
'taxon:' || id,
canonical_label,
'public.taxonomy_species',
id,
jsonb_build_object(
'canonical_label',canonical_label,
'genus',genus_name,
'species_epithet',species_epithet
),
TRUE,
v_run_id,
now()
FROM public.taxonomy_species;

-------------------------------------------------
-- TRAIT NODES
-------------------------------------------------

INSERT INTO oc_graph.kg_nodes
(
node_type,
canonical_key,
display_label,
source_table,
source_pk,
payload_json,
is_active,
build_run_id,
created_at
)
SELECT
'trait',
'trait:' || trait_id,
trait_name,
'public.traits',
trait_id,
jsonb_build_object(
'trait_name',trait_name
),
TRUE,
v_run_id,
now()
FROM public.traits;

-------------------------------------------------

UPDATE oc_graph.kg_build_runs
SET
status='completed',
completed_at=now()
WHERE build_run_id=v_run_id;

RETURN 'graph build finished';

END;
$$;

SELECT oc_graph.build_graph_from_normalized();

SELECT
node_type,
COUNT(*)
FROM oc_graph.kg_nodes
GROUP BY node_type
ORDER BY node_type;

SQL

echo
echo "Graph builder v5 installed and executed."
echo