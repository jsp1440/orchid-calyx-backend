#!/usr/bin/env bash
set -euo pipefail

echo
echo "Installing oc_graph.system_status monitoring..."
echo

psql "$DATABASE_URL" <<'SQL'

CREATE SCHEMA IF NOT EXISTS oc_graph;

CREATE TABLE IF NOT EXISTS oc_graph.system_status
(
    status_id BIGSERIAL PRIMARY KEY,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    overall_status TEXT NOT NULL DEFAULT 'unknown',
    notes TEXT,

    total_nodes BIGINT DEFAULT 0,
    total_edges BIGINT DEFAULT 0,

    taxon_nodes BIGINT DEFAULT 0,
    record_nodes BIGINT DEFAULT 0,
    image_nodes BIGINT DEFAULT 0,
    trait_nodes BIGINT DEFAULT 0,
    climate_nodes BIGINT DEFAULT 0,
    elevation_nodes BIGINT DEFAULT 0,
    atlas_cell_nodes BIGINT DEFAULT 0,

    orphan_nodes BIGINT DEFAULT 0,
    orphan_images BIGINT DEFAULT 0,
    unresolved_taxonomy BIGINT DEFAULT 0,

    conflicts_open BIGINT DEFAULT 0,

    last_build_time TIMESTAMPTZ,
    last_build_status TEXT,
    last_build_name TEXT,

    metrics_json JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_system_status_time
ON oc_graph.system_status(captured_at DESC);

CREATE OR REPLACE VIEW oc_graph.v_latest_system_status AS
SELECT *
FROM oc_graph.system_status
ORDER BY captured_at DESC
LIMIT 1;

CREATE OR REPLACE FUNCTION oc_graph.refresh_system_status()
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    v_status_id BIGINT;

    v_total_nodes BIGINT;
    v_total_edges BIGINT;

    v_taxon_nodes BIGINT;
    v_record_nodes BIGINT;
    v_image_nodes BIGINT;
    v_trait_nodes BIGINT;
    v_climate_nodes BIGINT;
    v_elevation_nodes BIGINT;
    v_atlas_cell_nodes BIGINT;

    v_orphan_nodes BIGINT;
    v_orphan_images BIGINT;
    v_unresolved_taxonomy BIGINT;
    v_conflicts_open BIGINT;

    v_last_build_time TIMESTAMPTZ;
    v_last_build_status TEXT;
    v_last_build_name TEXT;
BEGIN

    SELECT COUNT(*) INTO v_total_nodes
    FROM oc_graph.kg_nodes
    WHERE is_active IS TRUE;

    SELECT COUNT(*) INTO v_total_edges
    FROM oc_graph.kg_edges
    WHERE is_active IS TRUE;

    SELECT COUNT(*) INTO v_taxon_nodes
    FROM oc_graph.kg_nodes
    WHERE node_type='taxon' AND is_active IS TRUE;

    SELECT COUNT(*) INTO v_record_nodes
    FROM oc_graph.kg_nodes
    WHERE node_type='record' AND is_active IS TRUE;

    SELECT COUNT(*) INTO v_image_nodes
    FROM oc_graph.kg_nodes
    WHERE node_type='image' AND is_active IS TRUE;

    SELECT COUNT(*) INTO v_trait_nodes
    FROM oc_graph.kg_nodes
    WHERE node_type='trait' AND is_active IS TRUE;

    SELECT COUNT(*) INTO v_climate_nodes
    FROM oc_graph.kg_nodes
    WHERE node_type='climate_profile' AND is_active IS TRUE;

    SELECT COUNT(*) INTO v_elevation_nodes
    FROM oc_graph.kg_nodes
    WHERE node_type='elevation_profile' AND is_active IS TRUE;

    SELECT COUNT(*) INTO v_atlas_cell_nodes
    FROM oc_graph.kg_nodes
    WHERE node_type='atlas_cell' AND is_active IS TRUE;

    SELECT COUNT(*) INTO v_orphan_nodes
    FROM oc_graph.kg_nodes n
    WHERE NOT EXISTS (
        SELECT 1
        FROM oc_graph.kg_edges e
        WHERE e.from_node_id = n.kg_node_id
           OR e.to_node_id = n.kg_node_id
    );

    SELECT COUNT(*) INTO v_orphan_images
    FROM oc_graph.kg_nodes n
    WHERE node_type='image'
      AND NOT EXISTS (
        SELECT 1
        FROM oc_graph.kg_edges e
        WHERE e.from_node_id = n.kg_node_id
      );

    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_name='unresolved_taxonomy_names'
    ) THEN
        EXECUTE 'SELECT COUNT(*) FROM unresolved_taxonomy_names'
        INTO v_unresolved_taxonomy;
    ELSE
        v_unresolved_taxonomy := 0;
    END IF;

    SELECT COUNT(*) INTO v_conflicts_open
    FROM oc_graph.kg_conflict_log
    WHERE resolution_status='open';

    SELECT completed_at, status, build_name
    INTO v_last_build_time, v_last_build_status, v_last_build_name
    FROM oc_graph.kg_build_runs
    ORDER BY started_at DESC
    LIMIT 1;

    INSERT INTO oc_graph.system_status
    (
        overall_status,
        total_nodes,
        total_edges,
        taxon_nodes,
        record_nodes,
        image_nodes,
        trait_nodes,
        climate_nodes,
        elevation_nodes,
        atlas_cell_nodes,
        orphan_nodes,
        orphan_images,
        unresolved_taxonomy,
        conflicts_open,
        last_build_time,
        last_build_status,
        last_build_name,
        metrics_json
    )
    VALUES
    (
        'captured',
        v_total_nodes,
        v_total_edges,
        v_taxon_nodes,
        v_record_nodes,
        v_image_nodes,
        v_trait_nodes,
        v_climate_nodes,
        v_elevation_nodes,
        v_atlas_cell_nodes,
        v_orphan_nodes,
        v_orphan_images,
        v_unresolved_taxonomy,
        v_conflicts_open,
        v_last_build_time,
        v_last_build_status,
        v_last_build_name,
        jsonb_build_object(
            'captured_at', now(),
            'source', 'refresh_system_status'
        )
    )
    RETURNING status_id INTO v_status_id;

    RETURN v_status_id;

END;
$$;

SELECT oc_graph.refresh_system_status();

SELECT
status_id,
captured_at,
total_nodes,
total_edges,
orphan_nodes,
orphan_images,
unresolved_taxonomy,
conflicts_open
FROM oc_graph.v_latest_system_status;

SQL

echo
echo "oc_graph.system_status installed"
echo