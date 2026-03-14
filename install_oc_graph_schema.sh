#!/usr/bin/env bash
set -euo pipefail

echo
echo "Installing Orchid Continuum Graph Infrastructure..."
echo

psql "$DATABASE_URL" <<'SQL'

CREATE SCHEMA IF NOT EXISTS oc_graph;

-- ============================================================
-- GRAPH NODES
-- ============================================================

CREATE TABLE IF NOT EXISTS oc_graph.kg_nodes
(
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

CREATE INDEX IF NOT EXISTS idx_kg_nodes_type
ON oc_graph.kg_nodes(node_type);

CREATE INDEX IF NOT EXISTS idx_kg_nodes_key
ON oc_graph.kg_nodes(canonical_key);

CREATE INDEX IF NOT EXISTS idx_kg_nodes_payload
ON oc_graph.kg_nodes USING GIN(payload_json);

-- ============================================================
-- GRAPH EDGES
-- ============================================================

CREATE TABLE IF NOT EXISTS oc_graph.kg_edges
(
    kg_edge_id BIGSERIAL PRIMARY KEY,

    edge_type TEXT NOT NULL,

    from_node_id BIGINT NOT NULL,
    to_node_id BIGINT NOT NULL,

    source_table TEXT,
    source_pk TEXT,
    source_pk_json JSONB,

    evidence_class TEXT NOT NULL,

    confidence_score NUMERIC(5,4),
    confidence_label TEXT,

    rule_name TEXT,

    payload_json JSONB DEFAULT '{}'::jsonb,

    is_active BOOLEAN DEFAULT TRUE,

    build_run_id BIGINT,

    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT fk_edge_from_node
        FOREIGN KEY (from_node_id)
        REFERENCES oc_graph.kg_nodes(kg_node_id),

    CONSTRAINT fk_edge_to_node
        FOREIGN KEY (to_node_id)
        REFERENCES oc_graph.kg_nodes(kg_node_id)
);

CREATE INDEX IF NOT EXISTS idx_kg_edges_type
ON oc_graph.kg_edges(edge_type);

CREATE INDEX IF NOT EXISTS idx_kg_edges_from
ON oc_graph.kg_edges(from_node_id);

CREATE INDEX IF NOT EXISTS idx_kg_edges_to
ON oc_graph.kg_edges(to_node_id);

CREATE INDEX IF NOT EXISTS idx_kg_edges_payload
ON oc_graph.kg_edges USING GIN(payload_json);

-- ============================================================
-- BUILD RUN TRACKING
-- ============================================================

CREATE TABLE IF NOT EXISTS oc_graph.kg_build_runs
(
    build_run_id BIGSERIAL PRIMARY KEY,

    build_name TEXT NOT NULL,
    build_scope TEXT,

    started_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ,

    status TEXT NOT NULL,

    source_snapshot_json JSONB DEFAULT '{}'::jsonb,
    metrics_json JSONB DEFAULT '{}'::jsonb,

    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_kg_build_runs_status
ON oc_graph.kg_build_runs(status);

-- ============================================================
-- NODE LINEAGE
-- ============================================================

CREATE TABLE IF NOT EXISTS oc_graph.kg_node_lineage
(
    lineage_id BIGSERIAL PRIMARY KEY,

    kg_node_id BIGINT NOT NULL,

    source_table TEXT NOT NULL,
    source_pk TEXT,

    transformation_rule TEXT,

    build_run_id BIGINT,

    created_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- EDGE LINEAGE
-- ============================================================

CREATE TABLE IF NOT EXISTS oc_graph.kg_edge_lineage
(
    lineage_id BIGSERIAL PRIMARY KEY,

    kg_edge_id BIGINT NOT NULL,

    source_table TEXT NOT NULL,
    source_pk TEXT,

    transformation_rule TEXT,

    build_run_id BIGINT,

    created_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- CONFLICT LOG
-- ============================================================

CREATE TABLE IF NOT EXISTS oc_graph.kg_conflict_log
(
    conflict_id BIGSERIAL PRIMARY KEY,

    conflict_type TEXT NOT NULL,
    node_or_edge_type TEXT,

    source_a_json JSONB,
    source_b_json JSONB,

    resolution_status TEXT DEFAULT 'open',

    build_run_id BIGINT,

    created_at TIMESTAMPTZ DEFAULT now(),
    resolved_at TIMESTAMPTZ,

    resolution_notes TEXT
);

-- ============================================================
-- QUALITY METRICS
-- ============================================================

CREATE TABLE IF NOT EXISTS oc_graph.kg_quality_metrics
(
    metric_id BIGSERIAL PRIMARY KEY,

    metric_name TEXT NOT NULL,
    metric_scope TEXT,

    metric_value NUMERIC,

    metric_json JSONB DEFAULT '{}'::jsonb,

    build_run_id BIGINT,

    created_at TIMESTAMPTZ DEFAULT now()
);

SQL

echo
echo "Graph infrastructure installed."
echo
echo "Schema: oc_graph"
echo
echo "Tables created:"
echo " - kg_nodes"
echo " - kg_edges"
echo " - kg_build_runs"
echo " - kg_node_lineage"
echo " - kg_edge_lineage"
echo " - kg_conflict_log"
echo " - kg_quality_metrics"
echo