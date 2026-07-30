BEGIN;

CREATE SCHEMA IF NOT EXISTS reasoning_ledger;

CREATE TABLE IF NOT EXISTS reasoning_ledger.ledger_heads (
    ledger_id varchar(36) PRIMARY KEY,
    schema_version text NOT NULL,
    owner_subject text NOT NULL,
    project_id uuid NOT NULL REFERENCES research_station.projects(project_id) ON DELETE RESTRICT,
    logical_key_hash char(64) NOT NULL,
    current_version integer NOT NULL CHECK (current_version >= 1),
    current_content_hash char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_reasoning_ledger_logical_key
        UNIQUE (owner_subject, project_id, logical_key_hash)
);

CREATE INDEX IF NOT EXISTS idx_reasoning_heads_owner_project
    ON reasoning_ledger.ledger_heads(owner_subject, project_id);

CREATE TABLE IF NOT EXISTS reasoning_ledger.ledger_revisions (
    revision_id varchar(36) PRIMARY KEY,
    ledger_id varchar(36) NOT NULL REFERENCES reasoning_ledger.ledger_heads(ledger_id) ON DELETE RESTRICT,
    version integer NOT NULL CHECK (version >= 1),
    owner_subject text NOT NULL,
    project_id uuid NOT NULL REFERENCES research_station.projects(project_id) ON DELETE RESTRICT,
    status text NOT NULL CHECK (status IN ('draft','in_progress','under_review','approved','blocked','published')),
    entry_count integer NOT NULL CHECK (entry_count >= 0),
    content_hash char(64) NOT NULL,
    canonical_payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_reasoning_ledger_revision UNIQUE (ledger_id, version),
    CONSTRAINT ck_reasoning_revision_scope CHECK (
        canonical_payload->>'tenant_id' = owner_subject
        AND canonical_payload->>'project_id' = project_id::text
        AND canonical_payload->>'ledger_id' = ledger_id
        AND (canonical_payload->>'version')::integer = version
    )
);

CREATE INDEX IF NOT EXISTS idx_reasoning_revisions_owner_project
    ON reasoning_ledger.ledger_revisions(owner_subject, project_id, ledger_id, version);

CREATE TABLE IF NOT EXISTS reasoning_ledger.audit_events (
    event_id varchar(36) PRIMARY KEY,
    ledger_id varchar(36) NOT NULL,
    ledger_version integer NOT NULL,
    owner_subject text NOT NULL,
    project_id uuid NOT NULL REFERENCES research_station.projects(project_id) ON DELETE RESTRICT,
    event_type text NOT NULL,
    actor_subject text NOT NULL,
    event_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_reasoning_audit_revision
        FOREIGN KEY (ledger_id, ledger_version)
        REFERENCES reasoning_ledger.ledger_revisions(ledger_id, version)
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_reasoning_audit_ledger
    ON reasoning_ledger.audit_events(ledger_id, ledger_version, occurred_at);

COMMIT;
