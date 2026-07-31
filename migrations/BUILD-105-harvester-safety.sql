-- BUILD-105 — additive harvester safety telemetry and dead-letter support.
-- Generated only; do not execute automatically.

CREATE SCHEMA IF NOT EXISTS oc_admin;

CREATE TABLE IF NOT EXISTS oc_admin.harvest_safety_state (
    harvester_id text PRIMARY KEY,
    last_cursor text,
    consecutive_empty_pages integer NOT NULL DEFAULT 0,
    circuit_open boolean NOT NULL DEFAULT false,
    circuit_reason text,
    cooldown_until timestamptz,
    last_run_mode text,
    last_budget jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_audit jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS oc_admin.harvest_dead_letter (
    dead_letter_id bigserial PRIMARY KEY,
    harvester_id text NOT NULL,
    source_record_id text,
    reason text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    resolution_note text
);

CREATE INDEX IF NOT EXISTS harvest_dead_letter_harvester_created_idx
    ON oc_admin.harvest_dead_letter (harvester_id, created_at DESC);

CREATE INDEX IF NOT EXISTS harvest_dead_letter_unresolved_idx
    ON oc_admin.harvest_dead_letter (harvester_id, created_at DESC)
    WHERE resolved_at IS NULL;

-- Target-table constraints are intentionally not added here. Existing canonical
-- records/media schemas must be inventoried in the deployment database before
-- creating uniqueness indexes, to avoid blocking migration on legacy duplicates.
