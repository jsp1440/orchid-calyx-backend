BEGIN;
CREATE SCHEMA IF NOT EXISTS implementation_planning;
CREATE OR REPLACE FUNCTION implementation_planning.reject_immutable_change() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'BUILD-091 immutable artifact cannot be changed'; END $$;
CREATE TABLE IF NOT EXISTS implementation_planning.specification_sets(
 specification_id text PRIMARY KEY, logical_key text NOT NULL, version integer NOT NULL CHECK(version>0), integrity_hash text NOT NULL UNIQUE,
 lifecycle_state text NOT NULL CHECK(lifecycle_state IN ('DRAFT','REVIEW_REQUIRED','APPROVED','SUPERSEDED')),
 payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(logical_key,version));
CREATE TABLE IF NOT EXISTS implementation_planning.artifact_records(
 specification_id text NOT NULL REFERENCES implementation_planning.specification_sets(specification_id), artifact_type text NOT NULL,
 artifact_id text NOT NULL, payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(specification_id,artifact_type,artifact_id));
CREATE TABLE IF NOT EXISTS implementation_planning.reviews(
 review_id text PRIMARY KEY, specification_id text NOT NULL REFERENCES implementation_planning.specification_sets(specification_id),
 integrity_hash text NOT NULL UNIQUE,payload jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS implementation_planning.audit_events(
 event_id text PRIMARY KEY,specification_id text NOT NULL REFERENCES implementation_planning.specification_sets(specification_id),
 integrity_hash text NOT NULL UNIQUE,payload jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS idx_091_artifact_type ON implementation_planning.artifact_records(specification_id,artifact_type,artifact_id);
CREATE INDEX IF NOT EXISTS idx_091_spec_history ON implementation_planning.specification_sets(logical_key,version);
CREATE INDEX IF NOT EXISTS idx_091_review_spec ON implementation_planning.reviews(specification_id,created_at);
CREATE INDEX IF NOT EXISTS idx_091_audit_spec ON implementation_planning.audit_events(specification_id,created_at);
DO $$ DECLARE tab text; BEGIN FOREACH tab IN ARRAY ARRAY['specification_sets','artifact_records','reviews','audit_events'] LOOP
 EXECUTE format('DROP TRIGGER IF EXISTS immutable_091 ON implementation_planning.%I',tab);
 EXECUTE format('CREATE TRIGGER immutable_091 BEFORE UPDATE OR DELETE ON implementation_planning.%I FOR EACH ROW EXECUTE FUNCTION implementation_planning.reject_immutable_change()',tab);
END LOOP; END $$;
COMMIT;
