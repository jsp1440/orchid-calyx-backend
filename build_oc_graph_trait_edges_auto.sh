#!/usr/bin/env bash
set -euo pipefail

echo
echo "Auto-building Orchid Continuum graph trait nodes and edges..."
echo

psql "$DATABASE_URL" <<'SQL'
BEGIN;

CREATE SCHEMA IF NOT EXISTS oc_graph;

-- make sure graph tables exist
CREATE TABLE IF NOT EXISTS oc_graph.kg_nodes (
  kg_node_id BIGSERIAL PRIMARY KEY,
  node_type TEXT NOT NULL,
  canonical_key TEXT NOT NULL,
  display_label TEXT,
  source_table TEXT,
  source_pk TEXT,
  source_pk_json JSONB,
  evidence_class TEXT,
  confidence_score NUMERIC(5,4),
  confidence_label TEXT,
  payload_json JSONB DEFAULT '{}'::jsonb,
  is_active BOOLEAN DEFAULT TRUE,
  build_run_id BIGINT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  CONSTRAINT kg_nodes_unique UNIQUE (node_type, canonical_key)
);

CREATE TABLE IF NOT EXISTS oc_graph.kg_edges (
  kg_edge_id BIGSERIAL PRIMARY KEY,
  edge_type TEXT,
  from_key TEXT,
  to_key TEXT,
  source_table TEXT,
  source_pk TEXT,
  evidence_class TEXT DEFAULT 'normalized',
  confidence_score NUMERIC(5,4) DEFAULT 1.0000,
  confidence_label TEXT DEFAULT 'high',
  payload_json JSONB DEFAULT '{}'::jsonb,
  is_active BOOLEAN DEFAULT TRUE,
  build_run_id BIGINT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

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

DO $$
DECLARE
    v_run_id BIGINT;

    v_rtm_record_col TEXT;
    v_rtm_taxon_col  TEXT;

    v_rt_record_col  TEXT;
    v_rt_trait_id_col TEXT;
    v_rt_trait_label_col TEXT;

    v_sql TEXT;
BEGIN
    INSERT INTO oc_graph.kg_build_runs(build_name, status, notes)
    VALUES (
        'auto_trait_graph_build',
        'running',
        'Auto-discover columns in public.record_taxon_map and public.record_traits, then build trait nodes and taxon->trait edges'
    )
    RETURNING build_run_id INTO v_run_id;

    -- detect record_taxon_map record join column
    SELECT c.column_name
    INTO v_rtm_record_col
    FROM information_schema.columns c
    WHERE c