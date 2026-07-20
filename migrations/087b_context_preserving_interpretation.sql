CREATE SCHEMA IF NOT EXISTS oc_scientific_interpretation;

CREATE TABLE IF NOT EXISTS oc_scientific_interpretation.evidence_packets (
    packet_id BIGSERIAL PRIMARY KEY,
    packet_key TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    fingerprint TEXT NOT NULL UNIQUE,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (packet_key, version)
);

CREATE TABLE IF NOT EXISTS oc_scientific_interpretation.machine_interpretations (
    interpretation_id BIGSERIAL PRIMARY KEY,
    interpretation_key TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    fingerprint TEXT NOT NULL UNIQUE,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (interpretation_key, version)
);

CREATE TABLE IF NOT EXISTS oc_scientific_interpretation.routing_decisions (
    routing_decision_id BIGSERIAL PRIMARY KEY,
    interpretation_id BIGINT NOT NULL REFERENCES oc_scientific_interpretation.machine_interpretations(interpretation_id),
    policy_name TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    path TEXT NOT NULL CHECK (path IN ('AUTOMATIC_PROMOTION','PROVISIONAL_SCIENTIFIC_ASSERTION','EXCEPTION_REVIEW')),
    fingerprint TEXT NOT NULL UNIQUE,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_scientific_interpretation.canonical_assertions (
    assertion_id BIGSERIAL PRIMARY KEY,
    assertion_key TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    fingerprint TEXT NOT NULL UNIQUE,
    payload JSONB NOT NULL CHECK (payload @> '{"published": false}'::jsonb),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (assertion_key, version)
);

CREATE TABLE IF NOT EXISTS oc_scientific_interpretation.correction_records (
    correction_id BIGSERIAL PRIMARY KEY,
    correction_key TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    fingerprint TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (correction_key, version)
);

CREATE TABLE IF NOT EXISTS oc_scientific_interpretation.audit_events (
    event_id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    artifact_id BIGINT NOT NULL,
    actor TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS evidence_packets_key_idx ON oc_scientific_interpretation.evidence_packets(packet_key, version DESC);
CREATE INDEX IF NOT EXISTS interpretations_key_idx ON oc_scientific_interpretation.machine_interpretations(interpretation_key, version DESC);
CREATE INDEX IF NOT EXISTS routing_interpretation_idx ON oc_scientific_interpretation.routing_decisions(interpretation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS assertions_key_idx ON oc_scientific_interpretation.canonical_assertions(assertion_key, version DESC);
CREATE INDEX IF NOT EXISTS corrections_source_idx ON oc_scientific_interpretation.correction_records((payload->>'source_interpretation_id'));
CREATE INDEX IF NOT EXISTS interpretation_audit_idx ON oc_scientific_interpretation.audit_events(artifact_type, artifact_id, event_id);

CREATE OR REPLACE FUNCTION oc_scientific_interpretation.audit_artifact_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE artifact_id BIGINT;
BEGIN
    artifact_id := (to_jsonb(NEW)->>CASE TG_TABLE_NAME
        WHEN 'evidence_packets' THEN 'packet_id'
        WHEN 'machine_interpretations' THEN 'interpretation_id'
        WHEN 'routing_decisions' THEN 'routing_decision_id'
        WHEN 'canonical_assertions' THEN 'assertion_id'
        WHEN 'correction_records' THEN 'correction_id'
    END)::BIGINT;
    INSERT INTO oc_scientific_interpretation.audit_events(event_type, artifact_type, artifact_id, actor, details)
    VALUES ('ARTIFACT_APPENDED', UPPER(TG_TABLE_NAME), artifact_id, 'repository-trigger', jsonb_build_object('created_at', NEW.created_at));
    RETURN NEW;
END $$;

DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['evidence_packets','machine_interpretations','routing_decisions','canonical_assertions','correction_records']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'audit_' || table_name || '_insert') THEN
            EXECUTE format('CREATE TRIGGER %I AFTER INSERT ON oc_scientific_interpretation.%I FOR EACH ROW EXECUTE FUNCTION oc_scientific_interpretation.audit_artifact_insert()', 'audit_' || table_name || '_insert', table_name);
        END IF;
    END LOOP;
END $$;

CREATE OR REPLACE FUNCTION oc_scientific_interpretation.reject_artifact_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'SCIENTIFIC_ARTIFACTS_ARE_APPEND_ONLY';
END $$;

DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['evidence_packets','machine_interpretations','routing_decisions','canonical_assertions','correction_records','audit_events']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'protect_' || table_name || '_immutability') THEN
            EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON oc_scientific_interpretation.%I FOR EACH ROW EXECUTE FUNCTION oc_scientific_interpretation.reject_artifact_mutation()', 'protect_' || table_name || '_immutability', table_name);
        END IF;
    END LOOP;
END $$;
