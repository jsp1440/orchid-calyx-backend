-- CALYX-RECOVERY-001 Gate 2 — Calyx research executor durable tables.
--
-- These two tables were previously created at runtime by
-- runtime/calyx_research_executor.py with CREATE TABLE IF NOT EXISTS on every
-- write. Schema changes belong in migrations, not in request paths, so the DDL
-- lives here and the executor now reports (durability_degraded) instead of
-- masking a missing table.
--
-- calyx_research_projects: one JSON record per executor-created research
-- project, keyed by the project id and carrying the BUILD-051 request id.
-- calyx_research_state_history: append-only state transitions for a request.

CREATE SCHEMA IF NOT EXISTS oc_admin;

CREATE TABLE IF NOT EXISTS oc_admin.calyx_research_projects (
    id          TEXT PRIMARY KEY,
    request_id  TEXT NOT NULL,
    payload     JSONB NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_admin.calyx_research_state_history (
    id              BIGSERIAL PRIMARY KEY,
    request_id      TEXT NOT NULL,
    from_state      TEXT NOT NULL,
    to_state        TEXT NOT NULL,
    actor           TEXT,
    detail          JSONB,
    transitioned_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS calyx_research_state_history_request_idx
    ON oc_admin.calyx_research_state_history (request_id, id);
