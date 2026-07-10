-- BUILD-051 Owner Operations Console persistence.
-- Apply manually after backup. This migration is idempotent and non-destructive.
\set ON_ERROR_STOP on

BEGIN;

CREATE SCHEMA IF NOT EXISTS oc_admin;

CREATE TABLE IF NOT EXISTS oc_admin.build051_source_briefings (
    id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_admin.build051_intelligence_items (
    id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    created_by TEXT NOT NULL DEFAULT 'owner',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_admin.build051_owner_commands (
    id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_admin.build051_operations_queue (
    id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_admin.build051_research_requests (
    id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_admin.build051_generated_audits (
    id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_admin.build051_partnership_packets (
    id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_admin.build051_privileged_action_log (
    id TEXT PRIMARY KEY,
    actor TEXT NOT NULL,
    auth_type TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_build051_intelligence_status
    ON oc_admin.build051_intelligence_items ((payload->>'status'), updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_build051_intelligence_category
    ON oc_admin.build051_intelligence_items USING GIN ((payload->'category'));

CREATE INDEX IF NOT EXISTS idx_build051_commands_status
    ON oc_admin.build051_owner_commands ((payload->>'status'), created_at DESC);

CREATE INDEX IF NOT EXISTS idx_build051_queue_status
    ON oc_admin.build051_operations_queue ((payload->>'status'), created_at DESC);

CREATE INDEX IF NOT EXISTS idx_build051_research_status
    ON oc_admin.build051_research_requests ((payload->>'status'), created_at DESC);

CREATE INDEX IF NOT EXISTS idx_build051_action_log_actor
    ON oc_admin.build051_privileged_action_log (actor, created_at DESC);

COMMIT;
