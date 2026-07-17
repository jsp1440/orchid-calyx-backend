-- BUILD-076A: additive universal intake foundation. Apply after 070_knowledge_intake.sql.
CREATE TABLE IF NOT EXISTS oc_intake.ingestion_batches (
  id BIGSERIAL PRIMARY KEY, display_name TEXT NOT NULL, uploader TEXT, source_label TEXT,
  status TEXT NOT NULL, file_count INTEGER NOT NULL DEFAULT 0, accepted_count INTEGER NOT NULL DEFAULT 0,
  duplicate_count INTEGER NOT NULL DEFAULT 0, failed_count INTEGER NOT NULL DEFAULT 0,
  review_required_count INTEGER NOT NULL DEFAULT 0, notes TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  processing_started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS oc_intake.documents (
  id BIGSERIAL PRIMARY KEY, batch_id BIGINT NOT NULL REFERENCES oc_intake.ingestion_batches(id),
  original_filename TEXT NOT NULL, display_title TEXT NOT NULL, media_type TEXT, extension TEXT,
  byte_size BIGINT NOT NULL CHECK (byte_size >= 0), sha256 CHAR(64) NOT NULL, storage_key TEXT NOT NULL,
  uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), uploader TEXT, processing_status TEXT NOT NULL,
  text_extraction_status TEXT NOT NULL, extracted_text TEXT, extraction_error TEXT,
  preliminary_document_type TEXT NOT NULL, classification_confidence DOUBLE PRECISION,
  relevance TEXT NOT NULL, relevance_confidence DOUBLE PRECISION, relevance_explanation TEXT,
  review_status TEXT NOT NULL, duplicate_of_id BIGINT REFERENCES oc_intake.documents(id),
  possible_version_family TEXT, archive_only BOOLEAN NOT NULL DEFAULT FALSE,
  canonical_promotion_prohibited BOOLEAN NOT NULL DEFAULT TRUE, provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
  candidate_dates JSONB NOT NULL DEFAULT '[]'::jsonb, grant_candidate JSONB,
  external_sources JSONB NOT NULL DEFAULT '[]'::jsonb, reviewed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS intake_documents_batch_idx ON oc_intake.documents(batch_id, uploaded_at);
CREATE INDEX IF NOT EXISTS intake_documents_sha_idx ON oc_intake.documents(sha256);
CREATE INDEX IF NOT EXISTS intake_documents_review_idx ON oc_intake.documents(review_status, uploaded_at DESC);
CREATE TABLE IF NOT EXISTS oc_intake.document_events (
  id BIGSERIAL PRIMARY KEY, document_id BIGINT NOT NULL REFERENCES oc_intake.documents(id), action TEXT NOT NULL,
  previous_state JSONB, resulting_state JSONB, actor TEXT, occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  reason TEXT, origin TEXT NOT NULL CHECK (origin IN ('AUTOMATED','HUMAN'))
);
-- Rollback (explicit/manual): DROP TABLE oc_intake.document_events; DROP TABLE oc_intake.documents; DROP TABLE oc_intake.ingestion_batches;
