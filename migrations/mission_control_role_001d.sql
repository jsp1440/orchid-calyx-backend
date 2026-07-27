BEGIN;

CREATE SCHEMA IF NOT EXISTS oc_review;

CREATE TABLE IF NOT EXISTS oc_review.access_principal (
    principal_id TEXT PRIMARY KEY,
    authenticated BOOLEAN NOT NULL,
    roles JSONB NOT NULL DEFAULT '[]'::jsonb,
    direct_capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
    qualifications JSONB NOT NULL DEFAULT '[]'::jsonb,
    specialties JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_identity JSONB NOT NULL DEFAULT '{}'::jsonb,
    resolved_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS oc_review.review_task (
    task_id TEXT PRIMARY KEY,
    orchestration_id TEXT NOT NULL,
    review_type TEXT NOT NULL,
    risk_class TEXT NOT NULL,
    routing_outcome TEXT NOT NULL,
    required_capability TEXT NOT NULL,
    candidate_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    aggregate_version_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    priority INTEGER NOT NULL CHECK (priority BETWEEN 0 AND 100),
    scientific_impact_score DOUBLE PRECISION NOT NULL,
    consensus_required INTEGER NOT NULL CHECK (consensus_required >= 1),
    batch_key TEXT,
    display_policy TEXT,
    embargoed BOOLEAN NOT NULL DEFAULT FALSE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    state TEXT NOT NULL,
    assigned_to TEXT REFERENCES oc_review.access_principal(principal_id),
    reservation_expires_at TIMESTAMPTZ,
    authoritative_decision TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS review_task_queue_idx
ON oc_review.review_task (required_capability, state, priority DESC, scientific_impact_score DESC);

CREATE INDEX IF NOT EXISTS review_task_orchestration_idx
ON oc_review.review_task (orchestration_id);

CREATE TABLE IF NOT EXISTS oc_review.review_decision (
    decision_id BIGSERIAL PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES oc_review.review_task(task_id) ON DELETE RESTRICT,
    decision TEXT NOT NULL,
    reviewer_id TEXT NOT NULL REFERENCES oc_review.access_principal(principal_id),
    comment TEXT,
    modified_value JSONB,
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS review_decision_task_idx
ON oc_review.review_decision (task_id, decision_id);

CREATE TABLE IF NOT EXISTS oc_review.review_event (
    event_id BIGSERIAL PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES oc_review.review_task(task_id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS review_event_task_idx
ON oc_review.review_event (task_id, event_id);

COMMIT;
