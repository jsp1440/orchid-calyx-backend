BEGIN;
CREATE SCHEMA IF NOT EXISTS oc_workflow;

CREATE TABLE IF NOT EXISTS oc_workflow.actions (
    id BIGSERIAL PRIMARY KEY,
    source_id BIGINT NOT NULL REFERENCES oc_intake.sources(id) ON DELETE CASCADE,
    action_type TEXT NOT NULL CHECK (action_type IN (
        'TASK','CALENDAR','GRANT','TAXONOMY_REVIEW','LITERATURE_EXTRACTION',
        'PARTNERSHIP','CONNECTOR_REVIEW','MEDIA_SEARCH','ARCHIVE'
    )),
    destination TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    owner TEXT,
    priority TEXT NOT NULL DEFAULT 'MEDIUM' CHECK (priority IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','IN_PROGRESS','WAITING','COMPLETED','CANCELLED')),
    due_at TIMESTAMPTZ,
    reminder_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS oc_workflow.routing_history (
    id BIGSERIAL PRIMARY KEY,
    source_id BIGINT NOT NULL REFERENCES oc_intake.sources(id) ON DELETE CASCADE,
    action_id BIGINT REFERENCES oc_workflow.actions(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    actor TEXT,
    notes TEXT,
    event_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS workflow_actions_source_idx ON oc_workflow.actions(source_id, created_at DESC);
CREATE INDEX IF NOT EXISTS workflow_actions_status_idx ON oc_workflow.actions(status, priority, due_at);
CREATE INDEX IF NOT EXISTS workflow_actions_destination_idx ON oc_workflow.actions(destination, status);
CREATE INDEX IF NOT EXISTS workflow_routing_history_source_idx ON oc_workflow.routing_history(source_id, event_at DESC);
COMMIT;
