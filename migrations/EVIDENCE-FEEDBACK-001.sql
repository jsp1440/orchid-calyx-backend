-- EVIDENCE-FEEDBACK-001: evidence-feedback store schema and runtime grants.
--
-- Generated from app/evidence_feedback/postgres_repository.py SCHEMA_STATEMENTS
-- (which already include ADDITIVE_INDEXES). tests/test_evidence_feedback_grants_preflight.py
-- fails if this file and those statements drift apart; edit the Python first.
--
-- Additive and idempotent: every statement is CREATE ... IF NOT EXISTS. Nothing
-- here drops, truncates, alters or rewrites an existing object, so running it
-- again, or against a database the backend already bootstrapped, is a no-op.
--
-- NOT applied automatically. Applying it to production is an owner deployment
-- action. Run it as the schema owner, for example:
--   psql "$OWNER_DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/EVIDENCE-FEEDBACK-001.sql
-- then check the runtime role with scripts/preflight_evidence_feedback_grants.py.

BEGIN;

CREATE SCHEMA IF NOT EXISTS oc_evidence_feedback;

CREATE TABLE IF NOT EXISTS oc_evidence_feedback.object_versions(
    object_key TEXT NOT NULL CHECK (object_key <> ''),
    version_hash TEXT NOT NULL CHECK (version_hash ~ '^[0-9a-f]{64}$'),
    object_type TEXT NOT NULL,
    previous_version_hash TEXT,
    record_json TEXT NOT NULL,
    stored_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (object_key, version_hash)
);

CREATE TABLE IF NOT EXISTS oc_evidence_feedback.cases(
    case_key TEXT PRIMARY KEY CHECK (case_key <> ''),
    fingerprint TEXT NOT NULL,
    object_key TEXT NOT NULL,
    object_version_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    disposition TEXT NOT NULL,
    record_json TEXT NOT NULL,
    stored_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS oc_evidence_feedback.case_fingerprints(
    fingerprint_key TEXT PRIMARY KEY CHECK (fingerprint_key <> ''),
    case_key TEXT NOT NULL REFERENCES oc_evidence_feedback.cases(case_key),
    bound_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS oc_evidence_feedback.case_events(
    event_id BIGSERIAL PRIMARY KEY,
    case_key TEXT NOT NULL REFERENCES oc_evidence_feedback.cases(case_key),
    record_json TEXT NOT NULL,
    stored_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS case_events_case_idx ON oc_evidence_feedback.case_events(case_key, event_id);

CREATE INDEX IF NOT EXISTS cases_status_idx ON oc_evidence_feedback.cases(status, updated_at);

CREATE INDEX IF NOT EXISTS cases_review_order_idx ON oc_evidence_feedback.cases((((record_json::jsonb)->>'created_at') COLLATE "C") DESC, (case_key COLLATE "C") DESC);

COMMIT;

-- Runtime grants (commented out; the owner chooses the role).
-- The backend's runtime role needs exactly these to use tables it did not
-- create: USAGE on the schema, SELECT/INSERT/UPDATE on the tables (UPDATE for
-- the ON CONFLICT upserts; postgres_repository.py issues no DELETE) and USAGE on the
-- case_events sequence. Uncomment and run with psql, naming the role:
--   psql "$OWNER_DATABASE_URL" -v ON_ERROR_STOP=1 -v runtime_role=<role> -f <file holding them>
--
-- GRANT USAGE ON SCHEMA oc_evidence_feedback TO :"runtime_role";
-- GRANT SELECT, INSERT, UPDATE ON TABLE oc_evidence_feedback.object_versions TO :"runtime_role";
-- GRANT SELECT, INSERT, UPDATE ON TABLE oc_evidence_feedback.cases TO :"runtime_role";
-- GRANT SELECT, INSERT, UPDATE ON TABLE oc_evidence_feedback.case_fingerprints TO :"runtime_role";
-- GRANT SELECT, INSERT, UPDATE ON TABLE oc_evidence_feedback.case_events TO :"runtime_role";
-- GRANT USAGE ON ALL SEQUENCES IN SCHEMA oc_evidence_feedback TO :"runtime_role";
