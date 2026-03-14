#!/usr/bin/env bash
set -euo pipefail

psql "$DATABASE_URL" <<'SQL'
BEGIN;

INSERT INTO oc_graph.kg_edges
(
  edge_type,
  from_node_id,
  to_node_id,
  source_table,
  source_pk,
  source_pk_json,
  evidence_class,
  confidence_score,
  confidence_label,
  rule_name,
  payload_json,
  is_active,
  build_run_id,
  created_at,
  updated_at
)
SELECT
  'taxonomic_parent' AS edge_type,
  parent_node.kg_node_id AS from_node_id,
  child_node.kg_node_id  AS to_node_id,
  'public.taxonomy_species' AS source_table,
  child_ts.id::text AS source_pk,
  jsonb_build_object(
    'parent_species_id', parent_ts.id,
    'child_species_id', child_ts.id
  ) AS source_pk_json,
  'normalized' AS evidence_class,
  1.0000 AS confidence_score,
  'high' AS confidence_label,
  'taxonomy_parent_child_backbone' AS rule_name,
  jsonb_build_object(
    'parent_id', child_ts.parent_id,
    'child_id', child_ts.id
  ) AS payload_json,
  TRUE AS is_active,
  NULL::bigint AS build_run_id,
  now() AS created_at,
  now() AS updated_at
FROM public.taxonomy_species child_ts
JOIN public.taxonomy_species parent_ts
  ON parent_ts.id = child_ts.parent_id
JOIN oc_graph.kg_nodes parent_node
  ON parent_node.node_type = 'taxon'
 AND parent_node.canonical_key = 'taxon:' || parent_ts.id::text
JOIN oc_graph.kg_nodes child_node
  ON child_node.node_type = 'taxon'
 AND child_node.canonical_key = 'taxon:' || child_ts.id::text
WHERE child_ts.parent_id IS NOT NULL
  AND parent_node.kg_node_id <> child_node.kg_node_id
  AND NOT EXISTS (
    SELECT 1
    FROM oc_graph.kg_edges e
    WHERE e.edge_type = 'taxonomic_parent'
      AND e.from_node_id = parent_node.kg_node_id
      AND e.to_node_id = child_node.kg_node_id
  );

COMMIT;

SELECT 'nodes' AS section, COUNT(*)::bigint AS count
FROM oc_graph.kg_nodes
UNION ALL
SELECT 'edges', COUNT(*)::bigint
FROM oc_graph.kg_edges
UNION ALL
SELECT 'taxonomic_parent edges', COUNT(*)::bigint
FROM oc_graph.kg_edges
WHERE edge_type = 'taxonomic_parent';

SELECT edge_type, COUNT(*)::bigint AS count
FROM oc_graph.kg_edges
GROUP BY edge_type
ORDER BY edge_type;
SQL
