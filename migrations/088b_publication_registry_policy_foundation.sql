CREATE SCHEMA IF NOT EXISTS oc_knowledge_publication;

CREATE TABLE IF NOT EXISTS oc_knowledge_publication.policy_versions (
 policy_version_id BIGSERIAL PRIMARY KEY, policy_id TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0), name TEXT NOT NULL,
 rules JSONB NOT NULL, provenance JSONB NOT NULL, approval_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
 fingerprint TEXT NOT NULL UNIQUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(policy_id,version)
);
CREATE TABLE IF NOT EXISTS oc_knowledge_publication.policy_lifecycle_events (
 policy_event_id BIGSERIAL PRIMARY KEY, policy_version_id BIGINT NOT NULL REFERENCES oc_knowledge_publication.policy_versions,
 state TEXT NOT NULL CHECK(state IN('DRAFT','ACTIVE','RETIRED')), actor TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS oc_knowledge_publication.publication_candidates (
 publication_id BIGSERIAL PRIMARY KEY,
 publication_version INTEGER NOT NULL DEFAULT 1 CHECK(publication_version>0),
 assertion_id BIGINT NOT NULL REFERENCES oc_scientific_interpretation.canonical_assertions(assertion_id), assertion_version INTEGER NOT NULL CHECK(assertion_version>0),
 eligibility_decision_id BIGINT NOT NULL REFERENCES oc_scientific_interpretation.routing_decisions(routing_decision_id), eligibility_decision_version INTEGER NOT NULL CHECK(eligibility_decision_version=1),
 policy_version_id BIGINT NOT NULL REFERENCES oc_knowledge_publication.policy_versions,
 requested_pathway TEXT NOT NULL CHECK(requested_pathway IN('AUTOMATIC_GOVERNED_PUBLICATION','HUMAN_AUTHORIZED_PUBLICATION','PROVISIONAL_PUBLICATION')),
 idempotency_key TEXT NOT NULL UNIQUE, fingerprint TEXT NOT NULL UNIQUE, correlation_id TEXT NOT NULL, created_by TEXT NOT NULL,
 assertion_type TEXT NOT NULL, scientific_domain TEXT NOT NULL, taxonomy_concept_id TEXT, taxonomy_version TEXT,
 scientific_scope JSONB NOT NULL, qualifiers JSONB NOT NULL DEFAULT '{}'::jsonb,
 supporting_evidence_refs JSONB NOT NULL, conflicting_evidence_refs JSONB NOT NULL, provenance_root_refs JSONB NOT NULL,
 supersedes_publication_id BIGINT REFERENCES oc_knowledge_publication.publication_candidates, lineage JSONB NOT NULL DEFAULT '{}'::jsonb,
 immutable_metadata JSONB NOT NULL DEFAULT '{}'::jsonb, trusted_snapshot JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(publication_id,publication_version)
);
CREATE TABLE IF NOT EXISTS oc_knowledge_publication.lifecycle_transitions (
 transition_id BIGSERIAL PRIMARY KEY, publication_id BIGINT NOT NULL REFERENCES oc_knowledge_publication.publication_candidates,
 state TEXT NOT NULL CHECK(state IN('PUBLICATION_CANDIDATE','VALIDATING','AUTHORIZED','REJECTED')), actor TEXT NOT NULL,
 details JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS oc_knowledge_publication.authorization_decisions (
 decision_id BIGSERIAL PRIMARY KEY, publication_id BIGINT NOT NULL REFERENCES oc_knowledge_publication.publication_candidates,
 publication_version INTEGER NOT NULL, assertion_id BIGINT NOT NULL, assertion_version INTEGER NOT NULL,
 eligibility_decision_id BIGINT NOT NULL, eligibility_decision_version INTEGER NOT NULL,
 policy_version_id BIGINT NOT NULL REFERENCES oc_knowledge_publication.policy_versions,
 requested_pathway TEXT NOT NULL, resolved_pathway TEXT NOT NULL, outcome TEXT NOT NULL CHECK(outcome IN('AUTHORIZED','REJECTED','REVIEW_REQUIRED')),
 decision JSONB NOT NULL, fingerprint TEXT NOT NULL, actor TEXT NOT NULL, correlation_id TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(publication_id,fingerprint)
);
CREATE TABLE IF NOT EXISTS oc_knowledge_publication.audit_events (
 audit_event_id BIGSERIAL PRIMARY KEY, artifact_type TEXT NOT NULL, artifact_id BIGINT NOT NULL, event_type TEXT NOT NULL,
 actor TEXT NOT NULL, details JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS publication_candidate_assertion_idx ON oc_knowledge_publication.publication_candidates(assertion_id,assertion_version);
CREATE INDEX IF NOT EXISTS publication_transition_idx ON oc_knowledge_publication.lifecycle_transitions(publication_id,transition_id DESC);
CREATE INDEX IF NOT EXISTS publication_audit_idx ON oc_knowledge_publication.audit_events(artifact_type,artifact_id,audit_event_id);

CREATE OR REPLACE FUNCTION oc_knowledge_publication.reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'KNOWLEDGE_PUBLICATION_RECORDS_ARE_APPEND_ONLY'; END $$;
DO $$ DECLARE table_name TEXT; BEGIN
 FOREACH table_name IN ARRAY ARRAY['policy_versions','policy_lifecycle_events','publication_candidates','lifecycle_transitions','authorization_decisions','audit_events'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='protect_088b_'||table_name) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON oc_knowledge_publication.%I FOR EACH ROW EXECUTE FUNCTION oc_knowledge_publication.reject_mutation()','protect_088b_'||table_name,table_name);
  END IF;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION oc_knowledge_publication.enforce_lifecycle() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous TEXT;
BEGIN
 SELECT state INTO previous FROM oc_knowledge_publication.lifecycle_transitions WHERE publication_id=NEW.publication_id ORDER BY transition_id DESC LIMIT 1;
 IF (previous IS NULL AND NEW.state<>'PUBLICATION_CANDIDATE') OR
    (previous='PUBLICATION_CANDIDATE' AND NEW.state<>'VALIDATING') OR
    (previous='VALIDATING' AND NEW.state NOT IN('AUTHORIZED','REJECTED')) OR
    previous IN('AUTHORIZED','REJECTED') THEN RAISE EXCEPTION 'INVALID_PUBLICATION_LIFECYCLE_TRANSITION'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS enforce_088b_lifecycle ON oc_knowledge_publication.lifecycle_transitions;
CREATE TRIGGER enforce_088b_lifecycle BEFORE INSERT ON oc_knowledge_publication.lifecycle_transitions FOR EACH ROW EXECUTE FUNCTION oc_knowledge_publication.enforce_lifecycle();

CREATE OR REPLACE FUNCTION oc_knowledge_publication.enforce_policy_lifecycle() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous TEXT; logical_policy TEXT;
BEGIN
 SELECT policy_id INTO logical_policy FROM oc_knowledge_publication.policy_versions WHERE policy_version_id=NEW.policy_version_id;
 PERFORM pg_advisory_xact_lock(hashtextextended('policy-active:'||logical_policy,88));
 SELECT state INTO previous FROM oc_knowledge_publication.policy_lifecycle_events WHERE policy_version_id=NEW.policy_version_id ORDER BY policy_event_id DESC LIMIT 1;
 IF (previous IS NULL AND NEW.state<>'DRAFT') OR (previous='DRAFT' AND NEW.state<>'ACTIVE') OR (previous='ACTIVE' AND NEW.state<>'RETIRED') OR previous='RETIRED' THEN
  RAISE EXCEPTION 'INVALID_POLICY_LIFECYCLE_TRANSITION';
 END IF;
 IF NEW.state='ACTIVE' AND EXISTS(
   SELECT 1 FROM oc_knowledge_publication.policy_versions p WHERE p.policy_id=logical_policy AND p.policy_version_id<>NEW.policy_version_id
   AND (SELECT e.state FROM oc_knowledge_publication.policy_lifecycle_events e WHERE e.policy_version_id=p.policy_version_id ORDER BY e.policy_event_id DESC LIMIT 1)='ACTIVE'
 ) THEN RAISE EXCEPTION 'ACTIVE_POLICY_VERSION_ALREADY_EXISTS'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS enforce_088b_policy_lifecycle ON oc_knowledge_publication.policy_lifecycle_events;
CREATE TRIGGER enforce_088b_policy_lifecycle BEFORE INSERT ON oc_knowledge_publication.policy_lifecycle_events FOR EACH ROW EXECUTE FUNCTION oc_knowledge_publication.enforce_policy_lifecycle();

REVOKE UPDATE, DELETE ON ALL TABLES IN SCHEMA oc_knowledge_publication FROM PUBLIC;
