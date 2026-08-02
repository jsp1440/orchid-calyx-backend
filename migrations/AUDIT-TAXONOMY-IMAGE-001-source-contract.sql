\set ON_ERROR_STOP on

-- Read-only source contract inspection. This script performs no INSERT/UPDATE/DELETE.
-- Run before enabling a production population job so column mappings are explicit.

SELECT table_schema, table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE (table_schema, table_name) IN (
    ('oc_core', 'media_assets'),
    ('oc_core', 'record_media_link'),
    ('oc_graph', 'kg_nodes'),
    ('oc_admin', 'entity_relationship_links')
)
ORDER BY table_schema, table_name, ordinal_position;

SELECT
    to_regclass('oc_core.media_assets') AS media_assets,
    to_regclass('oc_core.record_media_link') AS record_media_link,
    to_regclass('oc_graph.kg_nodes') AS graph_nodes,
    to_regclass('oc_admin.entity_relationship_links') AS relationship_links;

-- The production writer must remain disabled until this inspection confirms:
-- 1. the stable media primary key;
-- 2. the record-domain and record-id columns;
-- 3. the canonical taxonomy identifier format;
-- 4. provider/license provenance columns;
-- 5. the BUILD-245 relationship table is present.
