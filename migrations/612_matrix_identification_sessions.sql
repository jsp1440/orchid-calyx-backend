-- CALYX-MATRIX-007 — Durable Matrix Identification sessions
--
-- Deployment boundary: this file defines the governed schema only. Merging the
-- migration does not imply that production has applied it or that durable mode
-- has been activated. Enable CALYX_MATRIX_SESSION_DURABLE_ENABLED only after
-- this migration is confirmed on the target PostgreSQL database.

BEGIN;

CREATE TABLE IF NOT EXISTS matrix_identification_sessions (
    session_id UUID PRIMARY KEY,
    owner TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    registry_id TEXT NOT NULL,
    registry_version TEXT NOT NULL,
    registry_checksum_sha256 TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    status TEXT NOT NULL DEFAULT 'active',
    record JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_matrix_identification_sessions_owner_updated
    ON matrix_identification_sessions(owner, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_matrix_identification_sessions_registry
    ON matrix_identification_sessions(registry_id, registry_version);

CREATE INDEX IF NOT EXISTS idx_matrix_identification_sessions_registry_checksum
    ON matrix_identification_sessions(registry_checksum_sha256);

COMMIT;
