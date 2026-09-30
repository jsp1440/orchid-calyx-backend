-- SHOW-GATE8-JUDGE-AUTH: per-judge credentials and the append-only judge audit.
--
-- Additive and idempotent: creates two tables, their indexes and an
-- append-only trigger if they do not already exist. It alters and drops no
-- existing table or column and touches no existing row. Requires the show
-- judging tables (shows, judges) to exist. Applying it to production remains
-- a separately governed owner action.
--
-- Mirrors app/models.py JudgeCredential and JudgeActionAudit. Timestamps are
-- naive UTC, like the other show tables.

CREATE TABLE IF NOT EXISTS judge_credentials (
    id VARCHAR(32) PRIMARY KEY,
    judge_id VARCHAR NOT NULL REFERENCES judges(id),
    show_id VARCHAR NOT NULL REFERENCES shows(id),
    token_hash VARCHAR(64) NOT NULL,
    event_ids_json TEXT,
    category_ids_json TEXT,
    label VARCHAR,
    issued_by VARCHAR,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITHOUT TIME ZONE
);

CREATE INDEX IF NOT EXISTS ix_judge_credentials_judge_id ON judge_credentials (judge_id);
CREATE INDEX IF NOT EXISTS ix_judge_credentials_show_id ON judge_credentials (show_id);

CREATE TABLE IF NOT EXISTS judge_action_audit (
    id VARCHAR PRIMARY KEY,
    judge_id VARCHAR NOT NULL,
    credential_id VARCHAR(32),
    action VARCHAR NOT NULL,
    judging_event_id VARCHAR,
    category_id VARCHAR,
    scorecard_id VARCHAR,
    plant_id VARCHAR,
    plant_handle VARCHAR,
    outcome VARCHAR NOT NULL,
    http_status INTEGER NOT NULL,
    detail TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_judge_action_audit_judge_id ON judge_action_audit (judge_id);
CREATE INDEX IF NOT EXISTS ix_judge_action_audit_credential_id ON judge_action_audit (credential_id);
CREATE INDEX IF NOT EXISTS ix_judge_action_audit_judging_event_id ON judge_action_audit (judging_event_id);
CREATE INDEX IF NOT EXISTS ix_judge_action_audit_created_at ON judge_action_audit (created_at);

CREATE OR REPLACE FUNCTION judge_action_audit_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'judge_action_audit is append-only';
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'judge_action_audit_no_update_delete'
    ) THEN
        CREATE TRIGGER judge_action_audit_no_update_delete
            BEFORE UPDATE OR DELETE ON judge_action_audit
            FOR EACH ROW EXECUTE FUNCTION judge_action_audit_append_only();
    END IF;
END;
$$;
