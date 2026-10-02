-- SHOW-GATE8-JUDGE-AUTH: per-judge credentials, the append-only judge and
-- owner audits, and blind display labels.
--
-- Additive and idempotent: creates three tables, their indexes and
-- append-only triggers if they do not already exist, and adds four nullable
-- columns (judging_events.blind_handle_salt, judging_events.blind_display_name,
-- plant_categories.blind_display_name, plants.blind_display_name) if missing.
-- It drops nothing, changes no existing column and touches no existing row.
-- Requires the show judging tables (shows, judges, judging_events,
-- plant_categories, plants). Applying it to production remains a separately
-- governed owner action.
--
-- Mirrors app/models.py JudgeCredential, JudgeActionAudit and ShowOwnerAudit.
-- Timestamps are naive UTC, like the other show tables.

ALTER TABLE judging_events ADD COLUMN IF NOT EXISTS blind_handle_salt VARCHAR(32);
ALTER TABLE judging_events ADD COLUMN IF NOT EXISTS blind_display_name TEXT;
ALTER TABLE plant_categories ADD COLUMN IF NOT EXISTS blind_display_name TEXT;
ALTER TABLE plants ADD COLUMN IF NOT EXISTS blind_display_name TEXT;

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

CREATE TABLE IF NOT EXISTS show_owner_audit (
    id VARCHAR PRIMARY KEY,
    actor VARCHAR NOT NULL,
    auth_type VARCHAR NOT NULL,
    action VARCHAR NOT NULL,
    object_type VARCHAR NOT NULL,
    object_id VARCHAR NOT NULL,
    show_id VARCHAR,
    judging_event_id VARCHAR,
    warnings_json TEXT,
    confirmed_despite_warnings BOOLEAN NOT NULL DEFAULT false,
    text_value TEXT,
    text_sha256 VARCHAR(64),
    text_withheld BOOLEAN NOT NULL DEFAULT false,
    detail TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_show_owner_audit_object_id ON show_owner_audit (object_id);
CREATE INDEX IF NOT EXISTS ix_show_owner_audit_show_id ON show_owner_audit (show_id);
CREATE INDEX IF NOT EXISTS ix_show_owner_audit_created_at ON show_owner_audit (created_at);

CREATE OR REPLACE FUNCTION judge_action_audit_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'judge_action_audit is append-only';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION show_owner_audit_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'show_owner_audit is append-only';
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    audit_table TEXT;
BEGIN
    FOREACH audit_table IN ARRAY ARRAY['judge_action_audit', 'show_owner_audit'] LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger
            WHERE tgname = audit_table || '_no_update_delete'
              AND tgrelid = audit_table::regclass
        ) THEN
            EXECUTE format(
                'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I '
                'FOR EACH ROW EXECUTE FUNCTION %I()',
                audit_table || '_no_update_delete', audit_table,
                audit_table || '_append_only'
            );
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger
            WHERE tgname = audit_table || '_no_truncate'
              AND tgrelid = audit_table::regclass
        ) THEN
            EXECUTE format(
                'CREATE TRIGGER %I BEFORE TRUNCATE ON %I '
                'FOR EACH STATEMENT EXECUTE FUNCTION %I()',
                audit_table || '_no_truncate', audit_table,
                audit_table || '_append_only'
            );
        END IF;
    END LOOP;
END;
$$;
