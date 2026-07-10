BEGIN;

CREATE SCHEMA IF NOT EXISTS oc_admin;

CREATE TABLE IF NOT EXISTS oc_admin.calyx_agents (
    id BIGSERIAL PRIMARY KEY,
    agent_name TEXT NOT NULL UNIQUE,
    capability TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    allowed_task_types JSONB NOT NULL DEFAULT '[]'::jsonb,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE oc_admin.calyx_agents
    ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS oc_admin.calyx_runtime_state (
    id INTEGER PRIMARY KEY DEFAULT 1,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by TEXT,
    CONSTRAINT calyx_runtime_state_singleton CHECK (id = 1)
);

INSERT INTO oc_admin.calyx_runtime_state (id, enabled, updated_by)
VALUES (1, FALSE, 'migration_default')
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS oc_admin.calyx_tasks (
    id BIGSERIAL PRIMARY KEY,
    task_key TEXT UNIQUE,
    task_type TEXT NOT NULL,
    title TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 0,
    required_approval BOOLEAN NOT NULL DEFAULT FALSE,
    approved_at TIMESTAMPTZ,
    assigned_agent_id BIGINT REFERENCES oc_admin.calyx_agents(id),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    last_error TEXT,
    evaluation_result TEXT,
    evaluation_details JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT calyx_tasks_status_check
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'blocked', 'needs_review')),
    CONSTRAINT calyx_tasks_eval_check
        CHECK (evaluation_result IS NULL OR evaluation_result IN ('pass', 'fail', 'needs_review'))
);

CREATE TABLE IF NOT EXISTS oc_admin.calyx_observations (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT REFERENCES oc_admin.calyx_tasks(id),
    agent_id BIGINT REFERENCES oc_admin.calyx_agents(id),
    event_type TEXT NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_admin.calyx_runs (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT REFERENCES oc_admin.calyx_tasks(id),
    agent_id BIGINT REFERENCES oc_admin.calyx_agents(id),
    status TEXT NOT NULL,
    evaluation_result TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_text TEXT
);

CREATE INDEX IF NOT EXISTS idx_calyx_tasks_status_priority
    ON oc_admin.calyx_tasks(status, priority DESC, id ASC);

CREATE INDEX IF NOT EXISTS idx_calyx_observations_task
    ON oc_admin.calyx_observations(task_id, id DESC);

COMMIT;
