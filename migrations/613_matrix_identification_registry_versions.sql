-- CALYX-MATRIX-017 — Durable immutable Matrix registry versions
--
-- Deployment boundary: merging this file does not apply it to production, copy
-- existing file-backed registries, or enable CALYX_MATRIX_REGISTRY_DURABLE_ENABLED.

BEGIN;

CREATE TABLE IF NOT EXISTS matrix_identification_registry_versions (
    registry_id TEXT NOT NULL,
    version TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL,
    publication_state TEXT NOT NULL DEFAULT 'review_required',
    record JSONB NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (registry_id, version)
);

CREATE INDEX IF NOT EXISTS idx_matrix_registry_checksum
    ON matrix_identification_registry_versions(checksum_sha256);

CREATE INDEX IF NOT EXISTS idx_matrix_registry_created_at
    ON matrix_identification_registry_versions(created_at DESC);

COMMIT;
