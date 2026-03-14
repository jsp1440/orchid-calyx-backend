#!/usr/bin/env bash
set -euo pipefail

psql "$DATABASE_URL" <<'SQL'
BEGIN;

CREATE SCHEMA IF NOT EXISTS oc_graph;

CREATE TABLE IF NOT EXISTS oc_graph.kg_edges (
  kg_edge_id BIGSERIAL PRIMARY KEY
);

ALTER TABLE oc_graph.kg_edges ADD COLUMN IF NOT EXISTS edge_type TEXT;
ALTER TABLE oc_graph.kg_edges ADD COLUMN IF NOT EXISTS from_key TEXT;
ALTER TABLE oc_graph.kg_edges ADD COLUMN IF NOT EXISTS to_key TEXT;
ALTER TABLE oc_graph.kg_edges ADD COLUMN IF NOT EXISTS source_table TEXT;
ALTER TABLE oc_graph.kg_edges ADD COLUMN IF NOT EXISTS source_pk TEXT;
ALTER TABLE oc_graph.kg_edges ADD COLUMN IF NOT EXISTS evidence_class TEXT DEFAULT 'normalized';
ALTER TABLE oc_graph.kg_edges ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(5,4) DEFAULT 1.0000;
ALTER TABLE oc_graph.kg_edges ADD COLUMN IF NOT EXISTS confidence_label TEXT DEFAULT 'high';
ALTER TABLE oc_graph.kg_edges ADD COLUMN IF NOT EXISTS payload_json JSONB DEFAULT '{}'::jsonb;
ALTER TABLE oc_graph.kg_edges ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
ALTER TABLE oc_graph.kg_edges ADD COLUMN IF NOT EXISTS build_run_id BIGINT;
ALTER TABLE oc_graph.kg_edges ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now();
ALTER TABLE oc_graph.kg_edges ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_kg_edges_from_key ON oc_graph.kg_edges (from_key);
CREATE INDEX IF NOT EXISTS idx_kg_edges_to_key   ON oc_graph.kg_edges (to_key);
CREATE INDEX IF NOT EXISTS idx_kg_edges_type     ON oc_graph.kg_edges (edge_type);
CREATE INDEX IF NOT EXISTS idx_kg_edges_payload  ON oc_graph.kg_edges USING GIN (payload_json);

CREATE UNIQUE INDEX IF NOT EXISTS uq_kg_edges_triplet
ON oc_graph.kg_edges (edge_type, from_key, to_key);

CREATE TABLE IF NOT EXISTS oc_graph.kg_build_runs (
  build_run_id BIGSERIAL PRIMARY KEY,
  build_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'running',
  notes TEXT,
  started_at TIMESTAMPTZ DEFAULT now(),
  completed_at TIMESTAMPTZ
);

WITH new_run AS (
  INSERT INTO oc_graph.kg_build_runs (build_name, status, notes)
  VALUES (
    'species_trait_edges_build_v2',
    'running',
    'Build species→trait edges from public.record_traits joined to public.record_taxon_map'
  )
  RETURNING build_run_id
),
inserted AS (
  INSERT INTO oc_graph.kg_edges (
    edge_type,
    from_key,
    to_key,
    source_table,
    source_pk,
    evidence_class,
    confidence_score,
    confidence_label,
    payload_json,
    is_active,
    build_run_id,
    created_at,
    updated_at
  )
  SELECT
    'has_trait' AS edge_type,
    'taxon:' || rtm.species_id::text AS from_key,
    'trait:' || rt.trait_id::text AS to_key,
    'public.record_traits' AS source_table,
    rt.record_id::text AS source_pk,
    'normalized' AS evidence_class,
    1.0000 AS confidence_score,
    'high' AS confidence_label,
    jsonb_build_object(
      'record_id', rt.record_id,
      'trait_id', rt.trait_id,
      'species_id', rtm.species_id
    ) AS payload_json,
    TRUE AS is_active,
    nr.build_run_id,
    now(),
    now()
  FROM public.record_traits rt
  JOIN public.record_taxon_map rtm
    ON rtm.record_id = rt.record_id
  CROSS JOIN new_run nr
  WHERE rtm.species_id IS NOT NULL
    AND rt.trait_id IS NOT NULL
  ON CONFLICT (edge_type, from_key, to_key) DO NOTHING
  RETURNING 1
)
UPDATE oc_graph.kg_build_runs br
SET status = 'completed',
    completed_at = now()
FROM new_run
WHERE br.build_run_id = new_run.build_run_id;

COMMIT;

SELECT 'kg_nodes total' AS section, COUNT(*)::bigint AS count
FROM oc_graph.kg_nodes
UNION ALL
SELECT 'kg_edges total', COUNT(*)::bigint
FROM oc_graph.kg_edges
UNION ALL
SELECT 'has_trait edges', COUNT(*)::bigint
FROM oc_graph.kg_edges
WHERE edge_type = 'has_trait';

SELECT edge_type, COUNT(*)::bigint AS count
FROM oc_graph.kg_edges
GROUP BY edge_type
ORDER BY edge_type;
SQL
