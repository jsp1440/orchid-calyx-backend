-- BUILD-082: additive controlled Drive document acquisition. Apply after 076A and 081.
CREATE SCHEMA IF NOT EXISTS oc_import;

CREATE TABLE IF NOT EXISTS oc_import.import_sessions (
  session_id BIGSERIAL PRIMARY KEY,
  authenticated_user TEXT NOT NULL,
  registry_ids BIGINT[] NOT NULL CHECK (cardinality(registry_ids) BETWEEN 1 AND 25),
  mission_id BIGINT REFERENCES oc_missions.missions(mission_id),
  importer_version TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('REGISTERED','READY','IMPORTING','IMPORTED','UNCHANGED','DUPLICATE','FAILED','RETRYABLE','CANCELLED')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  cancelled_at TIMESTAMPTZ, cancelled_by TEXT
);

CREATE TABLE IF NOT EXISTS oc_import.document_revisions (
  revision_id BIGSERIAL PRIMARY KEY,
  session_id BIGINT NOT NULL REFERENCES oc_import.import_sessions(session_id),
  registry_id BIGINT NOT NULL REFERENCES oc_sources.document_inventory(inventory_id),
  intake_document_id BIGINT NOT NULL REFERENCES oc_intake.documents(id),
  revision_number INTEGER NOT NULL CHECK (revision_number > 0),
  sha256 CHAR(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  byte_count BIGINT NOT NULL CHECK (byte_count >= 0),
  content_bytes BYTEA NOT NULL,
  provenance JSONB NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('IMPORTED','DUPLICATE')),
  duplicate_of_revision_id BIGINT REFERENCES oc_import.document_revisions(revision_id),
  imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(registry_id, revision_number)
);

CREATE TABLE IF NOT EXISTS oc_import.hash_index (
  sha256 CHAR(64) PRIMARY KEY CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  canonical_revision_id BIGINT NOT NULL REFERENCES oc_import.document_revisions(revision_id),
  byte_count BIGINT NOT NULL CHECK (byte_count >= 0), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_import.audit_trail (
  audit_id BIGSERIAL PRIMARY KEY, session_id BIGINT NOT NULL REFERENCES oc_import.import_sessions(session_id),
  registry_id BIGINT NOT NULL REFERENCES oc_sources.document_inventory(inventory_id),
  revision_id BIGINT REFERENCES oc_import.document_revisions(revision_id), previous_state TEXT,
  new_state TEXT NOT NULL CHECK (new_state IN ('REGISTERED','READY','IMPORTING','IMPORTED','UNCHANGED','DUPLICATE','FAILED','RETRYABLE','CANCELLED')),
  actor TEXT NOT NULL, reason TEXT, occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_import.retry_tracking (
  session_id BIGINT NOT NULL REFERENCES oc_import.import_sessions(session_id),
  registry_id BIGINT NOT NULL REFERENCES oc_sources.document_inventory(inventory_id),
  state TEXT NOT NULL CHECK (state IN ('FAILED','RETRYABLE','CANCELLED')),
  error_code TEXT NOT NULL, attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  last_attempt_at TIMESTAMPTZ, next_retry_at TIMESTAMPTZ, PRIMARY KEY(session_id, registry_id)
);

CREATE INDEX IF NOT EXISTS import_revision_registry_idx ON oc_import.document_revisions(registry_id, revision_number DESC);
CREATE INDEX IF NOT EXISTS import_revision_hash_idx ON oc_import.document_revisions(sha256);
CREATE INDEX IF NOT EXISTS import_audit_session_idx ON oc_import.audit_trail(session_id, occurred_at);
CREATE INDEX IF NOT EXISTS import_retry_due_idx ON oc_import.retry_tracking(next_retry_at) WHERE state='RETRYABLE';

COMMENT ON SCHEMA oc_import IS 'Immutable BUILD-082 Drive import revisions; semantic, ontology, embedding, and graph mutation are prohibited.';
COMMENT ON COLUMN oc_import.document_revisions.provenance IS 'Immutable import provenance. UPDATE and DELETE are prohibited by application policy.';

CREATE OR REPLACE FUNCTION oc_import.reject_immutable_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'BUILD-082 immutable records cannot be updated or deleted';
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='document_revisions_immutable') THEN
    CREATE TRIGGER document_revisions_immutable BEFORE UPDATE OR DELETE ON oc_import.document_revisions
      FOR EACH ROW EXECUTE FUNCTION oc_import.reject_immutable_mutation();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='import_audit_immutable') THEN
    CREATE TRIGGER import_audit_immutable BEFORE UPDATE OR DELETE ON oc_import.audit_trail
      FOR EACH ROW EXECUTE FUNCTION oc_import.reject_immutable_mutation();
  END IF;
END $$;
