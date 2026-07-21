CREATE SCHEMA IF NOT EXISTS oc_design_intelligence;

CREATE TABLE IF NOT EXISTS oc_design_intelligence.documents (
 document_id BIGSERIAL PRIMARY KEY,
 logical_key TEXT NOT NULL,
 version INTEGER NOT NULL CHECK(version > 0),
 title TEXT NOT NULL,
 document_type TEXT NOT NULL,
 authors JSONB NOT NULL,
 publication_date DATE,
 license_metadata JSONB NOT NULL,
 source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
 revision_id BIGINT NOT NULL REFERENCES oc_import.document_revisions(revision_id),
 extraction_run_id BIGINT NOT NULL REFERENCES oc_document_intelligence.extraction_runs(extraction_run_id),
 content_hash CHAR(64) NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(logical_key, version),
 UNIQUE(revision_id, extraction_run_id, content_hash)
);
CREATE TABLE IF NOT EXISTS oc_design_intelligence.document_provenance (
 provenance_id BIGSERIAL PRIMARY KEY,
 document_id BIGINT NOT NULL REFERENCES oc_design_intelligence.documents(document_id),
 source_system TEXT NOT NULL,
 source_id TEXT NOT NULL,
 revision_id BIGINT NOT NULL REFERENCES oc_import.document_revisions(revision_id),
 extraction_run_id BIGINT NOT NULL REFERENCES oc_document_intelligence.extraction_runs(extraction_run_id),
 anchor_id BIGINT NOT NULL REFERENCES oc_document_intelligence.source_anchors(anchor_id),
 evidence_link_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
 exact_locator JSONB NOT NULL DEFAULT '{}'::jsonb,
 fingerprint CHAR(64) NOT NULL UNIQUE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(document_id, anchor_id)
);
CREATE TABLE IF NOT EXISTS oc_design_intelligence.classifications (
 classification_id BIGSERIAL PRIMARY KEY,
 document_id BIGINT NOT NULL REFERENCES oc_design_intelligence.documents(document_id),
 domain TEXT NOT NULL CHECK(domain IN(
  'USER_EXPERIENCE','USER_INTERFACE','GRAPHIC_DESIGN','INFORMATION_ARCHITECTURE',
  'INTERACTION_DESIGN','DASHBOARD_DESIGN','ACCESSIBILITY','MOTION_AND_ANIMATION',
  'EDUCATIONAL_DESIGN','LEARNING_SCIENCES','SCIENTIFIC_VISUALIZATION',
  'BRANDING_AND_VISUAL_IDENTITY','DESIGN_SYSTEMS','COMPONENT_LIBRARIES')),
 knowledge_type TEXT NOT NULL CHECK(knowledge_type IN(
  'DESIGN_PRINCIPLE','PATTERN','ANTI_PATTERN','GUIDELINE','STANDARD','BEST_PRACTICE',
  'EDUCATIONAL_THEORY','ACCESSIBILITY_REQUIREMENT','VISUALIZATION_TECHNIQUE','INTERACTION_PATTERN')),
 confidence NUMERIC NOT NULL CHECK(confidence BETWEEN 0 AND 1),
 classifier_version TEXT NOT NULL,
 evidence JSONB NOT NULL,
 fingerprint CHAR(64) NOT NULL UNIQUE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(document_id, domain, knowledge_type, classifier_version)
);
CREATE TABLE IF NOT EXISTS oc_design_intelligence.topics (
 topic_id BIGSERIAL PRIMARY KEY,
 document_id BIGINT NOT NULL REFERENCES oc_design_intelligence.documents(document_id),
 topic TEXT NOT NULL,
 confidence NUMERIC NOT NULL CHECK(confidence BETWEEN 0 AND 1),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(document_id, topic)
);
CREATE TABLE IF NOT EXISTS oc_design_intelligence.review_events (
 review_event_id BIGSERIAL PRIMARY KEY,
 document_id BIGINT NOT NULL REFERENCES oc_design_intelligence.documents(document_id),
 state TEXT NOT NULL CHECK(state IN('APPROVED','CHANGES_REQUESTED','REJECTED')),
 actor TEXT NOT NULL,
 rationale TEXT NOT NULL,
 evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS oc_design_intelligence.publication_events (
 publication_event_id BIGSERIAL PRIMARY KEY,
 document_id BIGINT NOT NULL REFERENCES oc_design_intelligence.documents(document_id),
 status TEXT NOT NULL CHECK(status IN('PUBLISHED','RETIRED','RETRACTED')),
 actor TEXT NOT NULL,
 rationale TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS oc_design_intelligence.retrieval_documents (
 retrieval_document_id BIGSERIAL PRIMARY KEY,
 document_id BIGINT NOT NULL REFERENCES oc_design_intelligence.documents(document_id),
 anchor_id BIGINT NOT NULL REFERENCES oc_document_intelligence.source_anchors(anchor_id),
 authorized_text TEXT NOT NULL,
 search_vector TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', authorized_text)) STORED,
 display_policy TEXT NOT NULL,
 confidence NUMERIC NOT NULL CHECK(confidence BETWEEN 0 AND 1),
 fingerprint CHAR(64) NOT NULL UNIQUE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(document_id, anchor_id)
);
CREATE TABLE IF NOT EXISTS oc_design_intelligence.audit_events (
 audit_event_id BIGSERIAL PRIMARY KEY,
 document_id BIGINT REFERENCES oc_design_intelligence.documents(document_id),
 event_type TEXT NOT NULL,
 actor TEXT,
 details JSONB NOT NULL DEFAULT '{}'::jsonb,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS design_document_latest_idx ON oc_design_intelligence.documents(logical_key, version DESC);
CREATE INDEX IF NOT EXISTS design_classification_idx ON oc_design_intelligence.classifications(domain, knowledge_type, confidence DESC);
CREATE INDEX IF NOT EXISTS design_topic_idx ON oc_design_intelligence.topics(topic, confidence DESC);
CREATE INDEX IF NOT EXISTS design_review_idx ON oc_design_intelligence.review_events(document_id, review_event_id DESC);
CREATE INDEX IF NOT EXISTS design_publication_idx ON oc_design_intelligence.publication_events(document_id, publication_event_id DESC);
CREATE INDEX IF NOT EXISTS design_retrieval_fts_idx ON oc_design_intelligence.retrieval_documents USING GIN(search_vector);

CREATE OR REPLACE FUNCTION oc_design_intelligence.reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'DESIGN_INTELLIGENCE_RECORDS_ARE_APPEND_ONLY'; END $$;
DO $$ DECLARE table_name TEXT; BEGIN
 FOREACH table_name IN ARRAY ARRAY['documents','document_provenance','classifications','topics','review_events','publication_events','retrieval_documents','audit_events'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='protect_089a_'||table_name) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON oc_design_intelligence.%I FOR EACH ROW EXECUTE FUNCTION oc_design_intelligence.reject_mutation()','protect_089a_'||table_name,table_name);
  END IF;
 END LOOP;
END $$;
REVOKE UPDATE, DELETE ON ALL TABLES IN SCHEMA oc_design_intelligence FROM PUBLIC;
