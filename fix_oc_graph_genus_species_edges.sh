#!/usr/bin/env bash
set -euo pipefail

psql "$DATABASE_URL" <<'SQL'
BEGIN;

-- 1) Create real genus nodes
INSERT INTO oc_graph.kg_nodes
(
  node_type,
  canonical_key,
  display_label,
  source_table,
  source_pk,
  source_pk_json,
  evidence_class,
  confidence_score,
  confidence_label,
  payload_json,
  is_active,
  created_at,
  updated_at
)
SELECT
  'genus',
  'genus:' || g.id::text,
  g.genus_name,
  'public.taxonomy_genus',
  g.id::text,
  jsonb_build_object(
    'genus_id', g.id,
    'genus_name', g.genus_name,
    'subfamily_id', g.subfamily_id
  ),
  'normalized',
  1.0000,
  'high',
  '{}'::jsonb,
  TRUE,
  now(),
  now()
FROM public.taxonomy_genus g
ON CONFLICT (node_type, canonical_key) DO NOTHING;

-- 2) Remove the wrong edges we just built
DELETE FROM oc_graph.kg_edges
WHERE edge_type = 'genus_contains_species';

-- 3) Rebuild genus -> species edges correctly
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
  created_at,
  updated_at
)
SELECT
  'genus_contains_species',
  genus_node.kg_node_id,
  species_node.kg_node_id,
  'public.taxonomy_species',
  s.id::text,
  jsonb_build_object(
    'genus_id', s.genus_id,
    'species_id', s.id
  ),
  'normalized',
  1.0000,
  'high',
  'genus_species_backbone',
  '{}'::jsonb,
  TRUE,
  now(),
  now()
FROM public.taxonomy_species s
JOIN oc_graph.kg_nodes genus_node
  ON genus_node.node_type = 'genus'
 AND genus_node.canonical_key = 'genus:' || s.genus_id::text
JOIN oc_graph.kg_nodes species_node
  ON species_node.node_type = 'taxon'
 AND species_node.canonical_key = 'taxon:' || s.id::text
WHERE NOT EXISTS (
  SELECT 1
  FROM oc_graph.kg_edges e
  WHERE e.edge_type = 'genus_contains_species'
    AND e.from_node_id = genus_node.kg_node_id
    AND e.to_node_id = species_node.kg_node_id
);

COMMIT;

SELECT 'kg_nodes total' AS section, COUNT(*)::bigint AS count
FROM oc_graph.kg_nodes
UNION ALL
SELECT 'genus nodes', COUNT(*)::bigint
FROM oc_graph.kg_nodes
WHERE node_type = 'genus'
UNION ALL
SELECT 'species/taxon nodes', COUNT(*)::bigint
FROM oc_graph.kg_nodes
WHERE node_type = 'taxon'
UNION ALL
SELECT 'kg_edges total', COUNT(*)::bigint
FROM oc_graph.kg_edges
UNION ALL
SELECT 'genus_contains_species edges', COUNT(*)::bigint
FROM oc_graph.kg_edges
WHERE edge_type = 'genus_contains_species';

SELECT edge_type, COUNT(*)::bigint AS count
FROM oc_graph.kg_edges
GROUP BY edge_type
ORDER BY edge_type;

SQL
