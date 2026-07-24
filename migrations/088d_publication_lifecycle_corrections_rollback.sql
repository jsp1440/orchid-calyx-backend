CREATE TABLE IF NOT EXISTS oc_knowledge_publication.publication_lineage (
 lineage_id BIGSERIAL PRIMARY KEY, predecessor_publication_id BIGINT NOT NULL REFERENCES oc_knowledge_publication.publication_candidates,
 successor_publication_id BIGINT NOT NULL REFERENCES oc_knowledge_publication.publication_candidates,
 lineage_type TEXT NOT NULL CHECK(lineage_type IN('SUPERSESSION','CORRECTION')),
 prior_assertion_id BIGINT NOT NULL, prior_assertion_version INTEGER NOT NULL, successor_assertion_id BIGINT NOT NULL, successor_assertion_version INTEGER NOT NULL,
 correction_record_id BIGINT, reason_code TEXT NOT NULL, rationale TEXT NOT NULL, authority TEXT NOT NULL,
 fingerprint TEXT NOT NULL UNIQUE, correlation_id TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(predecessor_publication_id), CHECK(predecessor_publication_id<>successor_publication_id)
);
CREATE TABLE IF NOT EXISTS oc_knowledge_publication.publication_lifecycle_actions (
 action_id BIGSERIAL PRIMARY KEY, publication_id BIGINT NOT NULL REFERENCES oc_knowledge_publication.publication_candidates,
 action_type TEXT NOT NULL CHECK(action_type IN('WITHDRAWAL','RETRACTION','RESTORATION','REEVALUATION_REQUIRED','ROLLBACK_REQUIRED')),
 reason_code TEXT NOT NULL, rationale TEXT NOT NULL, invalidation_source JSONB NOT NULL DEFAULT '{}'::jsonb,
 authority TEXT NOT NULL, graph_transaction_id BIGINT, graph_version_id BIGINT, fingerprint TEXT NOT NULL UNIQUE,
 correlation_id TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS oc_knowledge_publication.publication_projection_events (
 projection_event_id BIGSERIAL PRIMARY KEY, publication_id BIGINT NOT NULL, graph_version_id BIGINT,
 projection TEXT NOT NULL CHECK(projection IN('AUTHORITATIVE_CURRENT','HISTORICAL','WITHDRAWN','RETRACTED','ROLLED_BACK')),
 included BOOLEAN NOT NULL, source_action_type TEXT NOT NULL, source_action_id BIGINT NOT NULL,
 fingerprint TEXT NOT NULL UNIQUE, correlation_id TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS oc_knowledge_publication.reevaluation_records (
 reevaluation_id BIGSERIAL PRIMARY KEY, trigger_publication_id BIGINT NOT NULL, affected_publication_id BIGINT NOT NULL,
 trigger_type TEXT NOT NULL, trigger_reference JSONB NOT NULL, affected_object_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
 status TEXT NOT NULL CHECK(status IN('OPEN','PROPAGATED')), fingerprint TEXT NOT NULL UNIQUE,
 correlation_id TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS oc_knowledge_publication.publication_dependencies (
 dependency_id BIGSERIAL PRIMARY KEY, source_publication_id BIGINT NOT NULL, dependent_publication_id BIGINT NOT NULL,
 dependency_type TEXT NOT NULL, fingerprint TEXT NOT NULL UNIQUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 CHECK(source_publication_id<>dependent_publication_id)
);
CREATE TABLE IF NOT EXISTS oc_knowledge_publication.propagation_checkpoints (
 checkpoint_id BIGSERIAL PRIMARY KEY, trigger_action_id BIGINT NOT NULL, batch_number INTEGER NOT NULL,
 visited_publication_ids JSONB NOT NULL, next_publication_ids JSONB NOT NULL, completed BOOLEAN NOT NULL,
 fingerprint TEXT NOT NULL UNIQUE, correlation_id TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(trigger_action_id,batch_number)
);
CREATE TABLE IF NOT EXISTS oc_knowledge_publication.downstream_impacts (
 impact_id BIGSERIAL PRIMARY KEY, source_action_type TEXT NOT NULL, source_action_id BIGINT NOT NULL,
 affected_publication_id BIGINT NOT NULL, affected_object_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
 consumer_category TEXT NOT NULL, required_action TEXT NOT NULL, action_status TEXT NOT NULL DEFAULT 'PENDING',
 retry_count INTEGER NOT NULL DEFAULT 0, fingerprint TEXT NOT NULL UNIQUE, correlation_id TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), completed_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS oc_knowledge_publication.rollback_manifests (
 rollback_id BIGSERIAL PRIMARY KEY, original_graph_transaction_id BIGINT NOT NULL UNIQUE,
 publication_id BIGINT NOT NULL, publication_version INTEGER NOT NULL, failed_graph_version_id BIGINT NOT NULL,
 coherent_graph_version_id BIGINT, rollback_reason TEXT NOT NULL, detection_source TEXT NOT NULL,
 inverse_operations JSONB NOT NULL, affected_node_ids JSONB NOT NULL, affected_edge_ids JSONB NOT NULL,
 affected_provenance_link_ids JSONB NOT NULL, affected_projections JSONB NOT NULL, preconditions JSONB NOT NULL,
 status TEXT NOT NULL CHECK(status='PREPARED'), fingerprint TEXT NOT NULL UNIQUE, service_identity TEXT NOT NULL,
 correlation_id TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS oc_knowledge_publication.rollback_transactions (
 rollback_transaction_id BIGSERIAL PRIMARY KEY, rollback_id BIGINT NOT NULL UNIQUE REFERENCES oc_knowledge_publication.rollback_manifests,
 original_graph_transaction_id BIGINT NOT NULL, restored_graph_version_id BIGINT, outcome TEXT NOT NULL CHECK(outcome='ROLLED_BACK'),
 fingerprint TEXT NOT NULL UNIQUE, service_identity TEXT NOT NULL, correlation_id TEXT NOT NULL,
 executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS publication_lineage_successor_idx ON oc_knowledge_publication.publication_lineage(successor_publication_id);
CREATE INDEX IF NOT EXISTS lifecycle_action_publication_idx ON oc_knowledge_publication.publication_lifecycle_actions(publication_id,action_id DESC);
CREATE INDEX IF NOT EXISTS projection_publication_idx ON oc_knowledge_publication.publication_projection_events(publication_id,projection_event_id DESC);
CREATE INDEX IF NOT EXISTS dependency_source_idx ON oc_knowledge_publication.publication_dependencies(source_publication_id,dependency_id);
CREATE INDEX IF NOT EXISTS impact_status_idx ON oc_knowledge_publication.downstream_impacts(action_status,impact_id);
CREATE OR REPLACE VIEW oc_knowledge_publication.current_publication_projection AS
 SELECT DISTINCT ON(publication_id) publication_id,graph_version_id,projection,included,source_action_type,source_action_id,created_at
 FROM oc_knowledge_publication.publication_projection_events ORDER BY publication_id,projection_event_id DESC;
CREATE OR REPLACE VIEW oc_knowledge_publication.authoritative_current_publications AS
 SELECT * FROM oc_knowledge_publication.current_publication_projection WHERE projection='AUTHORITATIVE_CURRENT' AND included;
CREATE OR REPLACE VIEW oc_knowledge_publication.withdrawn_publications AS
 SELECT * FROM oc_knowledge_publication.current_publication_projection WHERE projection='WITHDRAWN';
CREATE OR REPLACE VIEW oc_knowledge_publication.retracted_publications AS
 SELECT * FROM oc_knowledge_publication.current_publication_projection WHERE projection='RETRACTED';
INSERT INTO oc_knowledge_publication.publication_projection_events(
 publication_id,graph_version_id,projection,included,source_action_type,source_action_id,fingerprint,correlation_id
)
SELECT terminal.publication_id,
 latest_graph.graph_version_id,
 CASE terminal.state
  WHEN 'PUBLISHED' THEN 'AUTHORITATIVE_CURRENT'
  WHEN 'SUPERSEDED' THEN 'HISTORICAL'
  WHEN 'WITHDRAWN' THEN 'WITHDRAWN'
  WHEN 'RETRACTED' THEN 'RETRACTED'
  WHEN 'ROLLED_BACK' THEN 'ROLLED_BACK'
 END,
 CASE terminal.state
  WHEN 'PUBLISHED' THEN TRUE
  WHEN 'SUPERSEDED' THEN TRUE
  ELSE FALSE
 END,
 'MIGRATION_BACKFILL',
 terminal.transition_id,
 '088d-backfill-' || terminal.publication_id || '-' || terminal.transition_id,
 '088d-backfill-' || terminal.publication_id || '-' || terminal.transition_id
FROM (
 SELECT DISTINCT ON(publication_id) publication_id,state,transition_id
 FROM oc_knowledge_publication.lifecycle_transitions
 ORDER BY publication_id,transition_id DESC
) terminal
LEFT JOIN (
 SELECT DISTINCT ON(publication_id) publication_id,graph_version_id
 FROM oc_knowledge_publication.graph_versions
 ORDER BY publication_id,sequence DESC,graph_version_id DESC
) latest_graph ON latest_graph.publication_id=terminal.publication_id
WHERE terminal.state IN('PUBLISHED','SUPERSEDED','WITHDRAWN','RETRACTED','ROLLED_BACK')
AND NOT EXISTS (
 SELECT 1 FROM oc_knowledge_publication.publication_projection_events existing
 WHERE existing.publication_id=terminal.publication_id
)
ON CONFLICT(fingerprint) DO NOTHING;

ALTER TABLE oc_knowledge_publication.lifecycle_transitions DROP CONSTRAINT IF EXISTS lifecycle_transitions_state_check;
ALTER TABLE oc_knowledge_publication.lifecycle_transitions ADD CONSTRAINT lifecycle_transitions_state_check CHECK(state IN('PUBLICATION_CANDIDATE','VALIDATING','AUTHORIZED','REJECTED','TRANSACTION_PREPARED','PUBLISHING','PUBLISHED','PUBLICATION_FAILED','REEVALUATION_REQUIRED','SUPERSEDED','WITHDRAWN','RETRACTED','ROLLBACK_REQUIRED','ROLLED_BACK'));
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
 (previous='PUBLICATION_FAILED' AND NEW.state NOT IN('VALIDATING','REJECTED','ROLLBACK_REQUIRED')) OR
 (previous='PUBLISHED' AND NEW.state NOT IN('REEVALUATION_REQUIRED','SUPERSEDED','WITHDRAWN','RETRACTED','ROLLBACK_REQUIRED')) OR
 (previous='REEVALUATION_REQUIRED' AND NEW.state NOT IN('VALIDATING','SUPERSEDED','WITHDRAWN','RETRACTED')) OR
 (previous='WITHDRAWN' AND NEW.state<>'PUBLISHED') OR
 (previous='ROLLBACK_REQUIRED' AND NEW.state NOT IN('ROLLED_BACK','PUBLICATION_FAILED')) OR
 previous IN('REJECTED','SUPERSEDED','RETRACTED','ROLLED_BACK') THEN RAISE EXCEPTION 'INVALID_PUBLICATION_LIFECYCLE_TRANSITION'; END IF;
 RETURN NEW;
END $$;
DO $$ DECLARE table_name TEXT; BEGIN
 FOREACH table_name IN ARRAY ARRAY['publication_lineage','publication_lifecycle_actions','publication_projection_events','reevaluation_records','publication_dependencies','propagation_checkpoints','downstream_impacts','rollback_manifests','rollback_transactions'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='protect_088d_'||table_name) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON oc_knowledge_publication.%I FOR EACH ROW EXECUTE FUNCTION oc_knowledge_publication.reject_mutation()','protect_088d_'||table_name,table_name);
  END IF;
 END LOOP;
END $$;
REVOKE UPDATE,DELETE ON oc_knowledge_publication.publication_lineage,oc_knowledge_publication.publication_lifecycle_actions,
oc_knowledge_publication.publication_projection_events,oc_knowledge_publication.reevaluation_records,
oc_knowledge_publication.publication_dependencies,oc_knowledge_publication.propagation_checkpoints,
oc_knowledge_publication.downstream_impacts,oc_knowledge_publication.rollback_manifests,
oc_knowledge_publication.rollback_transactions FROM PUBLIC;
