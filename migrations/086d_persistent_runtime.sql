CREATE SCHEMA IF NOT EXISTS oc_candidate_knowledge;
CREATE TABLE IF NOT EXISTS oc_candidate_knowledge.runtime_repository_snapshots(
 repository_kind TEXT PRIMARY KEY CHECK(repository_kind IN('candidate_knowledge','evidence_aggregation')),
 state JSONB NOT NULL,
 revision BIGINT NOT NULL DEFAULT 1 CHECK(revision>0),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS oc_candidate_knowledge.runtime_repository_audit(
 audit_id BIGSERIAL PRIMARY KEY,
 repository_kind TEXT NOT NULL,
 revision BIGINT NOT NULL,
 event_type TEXT NOT NULL,
 actor TEXT NOT NULL,
 details JSONB NOT NULL DEFAULT '{}',
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS runtime_repository_audit_kind_idx ON oc_candidate_knowledge.runtime_repository_audit(repository_kind,revision,created_at);
CREATE OR REPLACE FUNCTION oc_candidate_knowledge.audit_runtime_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 INSERT INTO oc_candidate_knowledge.runtime_repository_audit(repository_kind,revision,event_type,actor,details)
 VALUES(NEW.repository_kind,NEW.revision,CASE WHEN TG_OP='INSERT' THEN 'SNAPSHOT_CREATED' ELSE 'SNAPSHOT_UPDATED' END,'build-086-runtime',jsonb_build_object('updated_at',NEW.updated_at));
 RETURN NEW;
END $$;
DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='runtime_repository_snapshot_audit') THEN
 CREATE TRIGGER runtime_repository_snapshot_audit AFTER INSERT OR UPDATE ON oc_candidate_knowledge.runtime_repository_snapshots FOR EACH ROW EXECUTE FUNCTION oc_candidate_knowledge.audit_runtime_snapshot();
END IF; END $$;
