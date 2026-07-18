-- BUILD-076B: review-only semantic extraction. Apply after 076a_universal_intake.sql.
CREATE SCHEMA IF NOT EXISTS oc_semantic;

CREATE TABLE IF NOT EXISTS oc_semantic.extraction_sessions (
  id BIGSERIAL PRIMARY KEY,
  document_id BIGINT NOT NULL REFERENCES oc_intake.documents(id),
  stage TEXT NOT NULL CHECK (stage IN ('QUEUED','PARSING','ENTITY_EXTRACTION','RELATIONSHIP_EXTRACTION','EVIDENCE_GENERATION','CANDIDATE_GENERATION','READY_FOR_REVIEW','FAILED')),
  created_by TEXT NOT NULL,
  provenance JSONB NOT NULL,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  canonical_promotion_prohibited BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS oc_semantic.evidence_objects (
  id BIGSERIAL PRIMARY KEY,
  session_id BIGINT NOT NULL REFERENCES oc_semantic.extraction_sessions(id) ON DELETE CASCADE,
  evidence_type TEXT NOT NULL,
  exact_text TEXT NOT NULL,
  start_offset INTEGER NOT NULL CHECK (start_offset >= 0),
  end_offset INTEGER NOT NULL CHECK (end_offset >= start_offset),
  source_sha256 CHAR(64) NOT NULL,
  provenance JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_semantic.candidates (
  id BIGSERIAL PRIMARY KEY,
  session_id BIGINT NOT NULL REFERENCES oc_semantic.extraction_sessions(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('ENTITY','RELATIONSHIP')),
  confidence DOUBLE PRECISION NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  review_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (review_status IN ('PENDING','ACCEPTED','REJECTED')),
  version INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  canonical_promotion_prohibited BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS oc_semantic.candidate_entities (
  candidate_id BIGINT PRIMARY KEY REFERENCES oc_semantic.candidates(id) ON DELETE CASCADE,
  entity_type TEXT NOT NULL,
  name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  start_offset INTEGER NOT NULL CHECK (start_offset >= 0),
  end_offset INTEGER NOT NULL CHECK (end_offset >= start_offset),
  attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS oc_semantic.candidate_relationships (
  candidate_id BIGINT PRIMARY KEY REFERENCES oc_semantic.candidates(id) ON DELETE CASCADE,
  subject_candidate_id BIGINT NOT NULL REFERENCES oc_semantic.candidate_entities(candidate_id),
  predicate TEXT NOT NULL,
  object_candidate_id BIGINT NOT NULL REFERENCES oc_semantic.candidate_entities(candidate_id),
  evidence_id BIGINT NOT NULL REFERENCES oc_semantic.evidence_objects(id),
  CHECK (subject_candidate_id <> object_candidate_id)
);

CREATE TABLE IF NOT EXISTS oc_semantic.reviews (
  id BIGSERIAL PRIMARY KEY,
  session_id BIGINT NOT NULL REFERENCES oc_semantic.extraction_sessions(id) ON DELETE CASCADE,
  decision TEXT NOT NULL CHECK (decision IN ('ACCEPT','REJECT','NEEDS_REVISION')),
  actor TEXT NOT NULL,
  notes TEXT,
  candidate_ids BIGINT[] NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  canonical_graph_mutated BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS oc_semantic.audit_events (
  id BIGSERIAL PRIMARY KEY,
  session_id BIGINT NOT NULL REFERENCES oc_semantic.extraction_sessions(id) ON DELETE CASCADE,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id BIGINT,
  previous_state JSONB,
  resulting_state JSONB,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS semantic_sessions_document_idx ON oc_semantic.extraction_sessions(document_id, created_at DESC);
CREATE INDEX IF NOT EXISTS semantic_candidates_session_idx ON oc_semantic.candidates(session_id, kind, review_status);
CREATE INDEX IF NOT EXISTS semantic_evidence_session_idx ON oc_semantic.evidence_objects(session_id, id);
CREATE INDEX IF NOT EXISTS semantic_audit_session_idx ON oc_semantic.audit_events(session_id, occurred_at, id);

CREATE OR REPLACE FUNCTION oc_semantic.reject_evidence_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'semantic evidence is immutable'; END $$;

DROP TRIGGER IF EXISTS semantic_evidence_immutable ON oc_semantic.evidence_objects;
CREATE TRIGGER semantic_evidence_immutable BEFORE UPDATE OR DELETE ON oc_semantic.evidence_objects
FOR EACH ROW EXECUTE FUNCTION oc_semantic.reject_evidence_mutation();
