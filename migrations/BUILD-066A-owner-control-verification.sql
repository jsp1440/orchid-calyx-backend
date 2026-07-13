-- BUILD-066A: Owner Control Verification table
-- Creates the persistent store for labeled owner control verification records.
-- This migration is idempotent (CREATE TABLE IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS oc_admin.build066a_control_verifications (
    id               TEXT        PRIMARY KEY,
    label            TEXT        NOT NULL,
    session_owner    TEXT        NOT NULL,
    read_back_confirmed BOOLEAN  NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE oc_admin.build066a_control_verifications
    IS 'BUILD-066A: Persistent store for labeled owner control verification records.';
