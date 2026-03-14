#!/usr/bin/env bash
set -euo pipefail

echo
echo "Installing Orchid Continuum Graph Builder (v2)..."
echo

psql "$DATABASE_URL" <<'SQL'

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
    (
        node_type,
        canonical_key,
        display_label,
        source_table,
        source_pk,
        evidence_class,
        confidence_score,
        confidence_label,
        payload_json,
        is_active,
        build_run_id,
        created_at
    )
    SELECT
        'taxon',
        'taxon:' || species_id,
        scientific_name,
        'taxonomy_species',
        species_id,
        'normalized',
        1.0,
        'high',
        jsonb_build_object(
            'scientific_name', scientific_name
        ),
        TRUE,
        v_run_id,
        now()
    FROM taxonomy_species
    ON CONFLICT DO NOTHING;

    ------------------------------------------------------------------
    -- IMAGE NODES
    ------------------------------------------------------------------

    INSERT INTO oc_graph.kg_nodes
    (
        node_type,
        canonical_key,
        display_label,
        source_table,
        source_pk,
        evidence_class,
        confidence_score,
        confidence_label,
        payload_json,
        is_active,
        build_run_id,
        created_at
    )
    SELECT
        'image',
        'image:' || asset_id,
        asset_url,
        'assets',
        asset_id,
        'normalized',
        0.9,
        'high',
        jsonb_build_object(
            'asset_url', asset_url
        ),
        TRUE,
        v_run_id,
        now()
    FROM assets
    ON CONFLICT DO NOTHING;

    ------------------------------------------------------------------
    -- TRAIT NODES
    ------------------------------------------------------------------

    INSERT INTO oc_graph.kg_nodes
    (
        node_type,
        canonical_key,
        display_label,
        source_table,
        source_pk,
        evidence_class,
        confidence_score,
        confidence_label,
        payload_json,
        is_active,
        build_run_id,
        created_at
    )
    SELECT
        'trait',
        'trait:' || trait_id,
        trait_name,
        'traits',
        trait_id,
        'normalized',
        0.95,
        'high',
        jsonb_build_object(
            'trait_name', trait_name
        ),
        TRUE,
        v_run_id,
        now()
    FROM traits
    ON CONFLICT DO NOTHING;

    ------------------------------------------------------------------
    -- COMPLETE BUILD
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
echo "Graph builder v2 installed and executed."
echo