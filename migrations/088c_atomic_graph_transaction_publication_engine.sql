CREATE TABLE IF NOT EXISTS oc_knowledge_publication.graph_change_sets (
 change_set_id BIGSERIAL PRIMARY KEY, version INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
 publication_id BIGINT NOT NULL REFERENCES oc_knowledge_publication.publication_candidates, publication_version INTEGER NOT NULL,
 authorization_decision_id BIGINT NOT NULL REFERENCES oc_knowledge_publication.authorization_decisions,
 assertion_id BIGINT NOT NULL, assertion_version INTEGER NOT NULL, policy_version_id BIGINT NOT NULL,
 source_graph_version_id BIGINT, operations JSONB NOT NULL, trusted_snapshot JSONB NOT NULL,
 validation_status TEXT NOT NULL CHECK(validation_status='VALIDATED'), fingerprint TEXT NOT NULL UNIQUE,
 created_by TEXT NOT NULL, correlation_id TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(change_set_id,version)
);
CREATE TABLE IF NOT EXISTS oc_knowledge_publication.graph_transaction_manifests (
 graph_transaction_id BIGSERIAL PRIMARY KEY, version INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
 change_set_id BIGINT NOT NULL REFERENCES oc_knowledge_publication.graph_change_sets, publication_id BIGINT NOT NULL,
 publication_version INTEGER NOT NULL, source_graph_version_id BIGINT, intended_target_sequence BIGINT NOT NULL,
 ordered_operations JSONB NOT NULL, validation_checks JSONB NOT NULL, status TEXT NOT NULL CHECK(status='PREPARED'),
 fingerprint TEXT NOT NULL UNIQUE, prior_attempt_id BIGINT, service_identity TEXT NOT NULL, correlation_id TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), prepared_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(graph_transaction_id,version)
);
CREATE TABLE IF NOT EXISTS oc_knowledge_publication.graph_versions (
 graph_version_id BIGSERIAL PRIMARY KEY, sequence BIGINT NOT NULL UNIQUE, parent_graph_version_id BIGINT REFERENCES oc_knowledge_publication.graph_versions,
 graph_transaction_id BIGINT NOT NULL UNIQUE REFERENCES oc_knowledge_publication.graph_transaction_manifests,
 publication_id BIGINT NOT NULL, publication_version INTEGER NOT NULL, status TEXT NOT NULL CHECK(status='COMMITTED'),
 node_change_count INTEGER NOT NULL, edge_change_count INTEGER NOT NULL, provenance_complete BOOLEAN NOT NULL CHECK(provenance_complete),
 fingerprint TEXT NOT NULL UNIQUE, correlation_id TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), committed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS oc_knowledge_publication.current_graph_version (
 singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK(singleton), graph_version_id BIGINT REFERENCES oc_knowledge_publication.graph_versions,
 sequence BIGINT NOT NULL DEFAULT 0, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO oc_knowledge_publication.current_graph_version(singleton,sequence) VALUES(TRUE,0) ON CONFLICT(singleton) DO NOTHING;
CREATE TABLE IF NOT EXISTS oc_knowledge_publication.graph_object_versions (
 object_version_id BIGSERIAL PRIMARY KEY, graph_version_id BIGINT NOT NULL REFERENCES oc_knowledge_publication.graph_versions,
 graph_transaction_id BIGINT NOT NULL, publication_id BIGINT NOT NULL, object_kind TEXT NOT NULL CHECK(object_kind IN('NODE','EDGE')),
 object_key TEXT NOT NULL, object_version INTEGER NOT NULL DEFAULT 1, legacy_object_id BIGINT NOT NULL, operation_type TEXT NOT NULL,
 payload JSONB NOT NULL, fingerprint TEXT NOT NULL UNIQUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(object_key,object_version)
);
CREATE TABLE IF NOT EXISTS oc_knowledge_publication.graph_provenance_links (
 provenance_link_id BIGSERIAL PRIMARY KEY, object_version_id BIGINT NOT NULL REFERENCES oc_knowledge_publication.graph_object_versions,
 graph_transaction_id BIGINT NOT NULL, publication_id BIGINT NOT NULL, authorization_decision_id BIGINT NOT NULL,
 assertion_id BIGINT NOT NULL, assertion_version INTEGER NOT NULL, interpretation_id BIGINT,
 evidence_packet_id BIGINT, source_revision_id BIGINT, provenance JSONB NOT NULL, fingerprint TEXT NOT NULL UNIQUE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS oc_knowledge_publication.graph_transaction_attempts (
 attempt_id BIGSERIAL PRIMARY KEY, graph_transaction_id BIGINT NOT NULL, attempt_number INTEGER NOT NULL,
 outcome TEXT NOT NULL CHECK(outcome IN('COMMITTED','FAILED','NO_OP_DUPLICATE')), reason_code TEXT NOT NULL,
 details JSONB NOT NULL DEFAULT '{}'::jsonb, actor TEXT NOT NULL, correlation_id TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(graph_transaction_id,attempt_number)
);
CREATE INDEX IF NOT EXISTS graph_change_publication_idx ON oc_knowledge_publication.graph_change_sets(publication_id,publication_version);
CREATE INDEX IF NOT EXISTS graph_transaction_publication_idx ON oc_knowledge_publication.graph_transaction_manifests(publication_id,publication_version);
CREATE INDEX IF NOT EXISTS graph_object_version_idx ON oc_knowledge_publication.graph_object_versions(object_key,object_version DESC);
CREATE INDEX IF NOT EXISTS graph_provenance_reverse_idx ON oc_knowledge_publication.graph_provenance_links(source_revision_id,assertion_id);

ALTER TABLE oc_knowledge_publication.lifecycle_transitions DROP CONSTRAINT IF EXISTS lifecycle_transitions_state_check;
ALTER TABLE oc_knowledge_publication.lifecycle_transitions ADD CONSTRAINT lifecycle_transitions_state_check CHECK(state IN('PUBLICATION_CANDIDATE','VALIDATING','AUTHORIZED','REJECTED','TRANSACTION_PREPARED','PUBLISHING','PUBLISHED','PUBLICATION_FAILED','ROLLBACK_REQUIRED')) NOT VALID;
CREATE OR REPLACE FUNCTION oc_knowledge_publication.enforce_lifecycle() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous TEXT;
BEGIN
 SELECT state INTO previous FROM oc_knowledge_publication.lifecycle_transitions WHERE publication_id=NEW.publication_id ORDER BY transition_id DESC LIMIT 1;
 IF (previous IS NULL AND NEW.state<>'PUBLICATION_CANDIDATE') OR
    (previous='PUBLICATION_CANDIDATE' AND NEW.state<>'VALIDATING') OR
    (previous='VALIDATING' AND NEW.state NOT IN('AUTHORIZED','REJECTED')) OR
    (previous='AUTHORIZED' AND NEW.state NOT IN('TRANSACTION_PREPARED','PUBLICATION_FAILED')) OR
    (previous='TRANSACTION_PREPARED' AND NEW.state NOT IN('PUBLISHING','PUBLICATION_FAILED')) OR
    (previous='PUBLISHING' AND NEW.state NOT IN('PUBLISHED','PUBLICATION_FAILED','ROLLBACK_REQUIRED')) OR
    previous IN('REJECTED','PUBLISHED','ROLLBACK_REQUIRED') THEN RAISE EXCEPTION 'INVALID_PUBLICATION_LIFECYCLE_TRANSITION'; END IF;
 RETURN NEW;
END $$;

DO $$ DECLARE table_name TEXT; BEGIN
 FOREACH table_name IN ARRAY ARRAY['graph_change_sets','graph_transaction_manifests','graph_versions','graph_object_versions','graph_provenance_links','graph_transaction_attempts'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='protect_088c_'||table_name) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON oc_knowledge_publication.%I FOR EACH ROW EXECUTE FUNCTION oc_knowledge_publication.reject_mutation()','protect_088c_'||table_name,table_name);
  END IF;
 END LOOP;
END $$;
REVOKE UPDATE, DELETE ON oc_knowledge_publication.graph_change_sets, oc_knowledge_publication.graph_transaction_manifests,
 oc_knowledge_publication.graph_versions, oc_knowledge_publication.graph_object_versions,
 oc_knowledge_publication.graph_provenance_links, oc_knowledge_publication.graph_transaction_attempts FROM PUBLIC;
