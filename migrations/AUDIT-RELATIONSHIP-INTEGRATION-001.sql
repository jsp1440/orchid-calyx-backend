BEGIN;

CREATE SCHEMA IF NOT EXISTS oc_admin;

CREATE TABLE IF NOT EXISTS oc_admin.entity_relationship_links (
    link_id BIGSERIAL PRIMARY KEY,
    source_domain TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    target_domain TEXT NOT NULL,
    target_record_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    taxon_id TEXT,
    match_method TEXT NOT NULL,
    confidence NUMERIC(5,4) NOT NULL DEFAULT 1.0
        CHECK (confidence >= 0 AND confidence <= 1),
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    validation_status TEXT NOT NULL DEFAULT 'provisional'
        CHECK (validation_status IN ('provisional', 'verified', 'rejected', 'superseded')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (
        source_domain,
        source_record_id,
        target_domain,
        target_record_id,
        relationship_type
    )
);

CREATE INDEX IF NOT EXISTS idx_entity_relationship_links_taxon
    ON oc_admin.entity_relationship_links (taxon_id);
CREATE INDEX IF NOT EXISTS idx_entity_relationship_links_domains
    ON oc_admin.entity_relationship_links (source_domain, target_domain);
CREATE INDEX IF NOT EXISTS idx_entity_relationship_links_status
    ON oc_admin.entity_relationship_links (validation_status);
CREATE INDEX IF NOT EXISTS idx_entity_relationship_links_provenance
    ON oc_admin.entity_relationship_links USING GIN (provenance);

CREATE OR REPLACE VIEW oc_admin.v_taxonomy_relationship_coverage AS
SELECT
    target_domain,
    COUNT(*) AS link_count,
    COUNT(DISTINCT taxon_id) FILTER (WHERE taxon_id IS NOT NULL) AS linked_taxa,
    COUNT(*) FILTER (WHERE validation_status = 'verified') AS verified_links,
    COUNT(*) FILTER (WHERE validation_status = 'provisional') AS provisional_links
FROM oc_admin.entity_relationship_links
WHERE source_domain = 'taxonomy'
GROUP BY target_domain;

CREATE OR REPLACE VIEW oc_admin.v_relationship_integrity_issues AS
SELECT
    link_id,
    source_domain,
    source_record_id,
    target_domain,
    target_record_id,
    relationship_type,
    CASE
        WHEN source_domain = target_domain AND source_record_id = target_record_id
            THEN 'self_loop'
        WHEN taxon_id IS NULL AND source_domain = 'taxonomy'
            THEN 'missing_taxon_id'
        WHEN provenance = '{}'::jsonb
            THEN 'missing_provenance'
        ELSE NULL
    END AS issue_type
FROM oc_admin.entity_relationship_links
WHERE
    (source_domain = target_domain AND source_record_id = target_record_id)
    OR (taxon_id IS NULL AND source_domain = 'taxonomy')
    OR provenance = '{}'::jsonb;

COMMIT;
