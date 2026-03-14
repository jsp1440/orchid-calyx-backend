#!/usr/bin/env bash
set -euo pipefail

echo
echo "Installing Orchid Continuum Graph Builder..."
echo

psql "$DATABASE_URL" <<'SQL'

CREATE SCHEMA IF NOT EXISTS oc_graph;

CREATE OR REPLACE FUNCTION oc_graph.build_graph_from_normalized()
RETURNS TEXT
LANGUAGE plpgsql
AS $$
DECLARE
    v_run_id BIGINT;
BEGIN

    INSERT INTO oc_graph.kg_build_runs
    (build_name, status, started_at)
    VALUES
    ('normalized_graph_build', 'running', now())
    RETURNING build_run_id INTO v_run_id;

    ------------------------------------------------------------------
    -- TAXON NODES
    ------------------------------------------------------------------

    INSERT INTO oc_graph.kg_nodes
    (node_type, source_table, source_id, label, created_at, is_active)
    SELECT
        'taxon',
        'taxonomy_species',
        species_id,
        scientific_name,
        now(),
        TRUE
    FROM taxonomy_species
    ON CONFLICT DO NOTHING;

    ------------------------------------------------------------------
    -- IMAGE NODES
    ------------------------------------------------------------------

    INSERT INTO oc_graph.kg_nodes
    (node_type, source_table, source_id, label, created_at, is_active)
    SELECT
        'image',
        'assets',
        asset_id,
        asset_url,
        now(),
        TRUE
    FROM assets
    ON CONFLICT DO NOTHING;

    ------------------------------------------------------------------
    -- TRAIT NODES
    ------------------------------------------------------------------

    INSERT INTO oc_graph.kg_nodes
    (node_type, source_table, source_id, label, created_at, is_active)
    SELECT
        'trait',
        'traits',
        trait_id,
        trait_name,
        now(),
        TRUE
    FROM traits
    ON CONFLICT DO NOTHING;

    ------------------------------------------------------------------
    -- CLIMATE PROFILE NODES
    ------------------------------------------------------------------

    INSERT INTO oc_graph.kg_nodes
    (node_type, source_table, source_id, label, created_at, is_active)
    SELECT
        'climate_profile',
        'climate_profiles',
        climate_id,
        location_name,
        now(),
        TRUE
    FROM climate_profiles
    ON CONFLICT DO NOTHING;

    ------------------------------------------------------------------
    -- ELEVATION PROFILE NODES
    ------------------------------------------------------------------

    INSERT INTO oc_graph.kg_nodes
    (node_type, source_table, source_id, label, created_at, is_active)
    SELECT
        'elevation_profile',
        'elevation_profiles',
        elevation_id,
        elevation_label,
        now(),
        TRUE
    FROM elevation_profiles
    ON CONFLICT DO NOTHING;

    ------------------------------------------------------------------
    -- ATLAS CELL NODES
    ------------------------------------------------------------------

    INSERT INTO oc_graph.kg_nodes
    (node_type, source_table, source_id, label, created_at, is_active)
    SELECT
        'atlas_cell',
        'atlas_cells',
        cell_id,
        cell_code,
        now(),
        TRUE
    FROM atlas_cells
    ON CONFLICT DO NOTHING;

    ------------------------------------------------------------------
    -- BUILD COMPLETE
    ------------------------------------------------------------------

    UPDATE oc_graph.kg_build_runs
    SET
        completed_at = now(),
        status = 'completed'
    WHERE build_run_id = v_run_id;

    RETURN 'Graph build completed';

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
echo "Graph builder installed and executed."
echo