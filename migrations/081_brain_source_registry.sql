-- BUILD-081: metadata-only Brain source registry and Google Drive inventory.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS oc_sources;

CREATE TABLE IF NOT EXISTS oc_sources.sources (
  source_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_name TEXT NOT NULL,
  source_type TEXT NOT NULL,
  authentication_method TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ACTIVE','PAUSED','ERROR')),
  last_scan TIMESTAMPTZ,
  total_documents BIGINT NOT NULL DEFAULT 0 CHECK (total_documents >= 0),
  total_processed BIGINT NOT NULL DEFAULT 0 CHECK (total_processed >= 0),
  total_failed BIGINT NOT NULL DEFAULT 0 CHECK (total_failed >= 0),
  configuration JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (source_name, source_type)
);

CREATE TABLE IF NOT EXISTS oc_sources.scan_logs (
  scan_id BIGSERIAL PRIMARY KEY,
  source_id UUID NOT NULL REFERENCES oc_sources.sources(source_id),
  status TEXT NOT NULL CHECK (status IN ('RUNNING','COMPLETED','COMPLETED_WITH_ERRORS','FAILED')),
  started_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ,
  duration_ms BIGINT,
  documents_processed BIGINT NOT NULL DEFAULT 0,
  documents_unchanged BIGINT NOT NULL DEFAULT 0,
  duplicates_found BIGINT NOT NULL DEFAULT 0,
  documents_failed BIGINT NOT NULL DEFAULT 0,
  error_message TEXT
);

CREATE TABLE IF NOT EXISTS oc_sources.document_inventory (
  inventory_id BIGSERIAL PRIMARY KEY,
  source_id UUID NOT NULL REFERENCES oc_sources.sources(source_id),
  external_file_id TEXT NOT NULL,
  filename TEXT NOT NULL,
  folder_path TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  byte_size BIGINT,
  checksum TEXT,
  created_at TIMESTAMPTZ,
  modified_at TIMESTAMPTZ,
  drive_version TEXT,
  native_duplicate_key CHAR(64),
  status TEXT NOT NULL CHECK (status IN ('NEW','SCANNED','PROCESSED','FAILED','DUPLICATE','CHANGED')),
  duplicate_of_id BIGINT REFERENCES oc_sources.document_inventory(inventory_id),
  first_seen_scan_id BIGINT NOT NULL REFERENCES oc_sources.scan_logs(scan_id),
  last_seen_scan_id BIGINT NOT NULL REFERENCES oc_sources.scan_logs(scan_id),
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  provenance JSONB NOT NULL,
  UNIQUE (source_id, external_file_id),
  CHECK (duplicate_of_id IS NULL OR status = 'DUPLICATE')
);

CREATE INDEX IF NOT EXISTS source_inventory_checksum_idx ON oc_sources.document_inventory(checksum) WHERE checksum IS NOT NULL;
CREATE INDEX IF NOT EXISTS source_inventory_native_key_idx ON oc_sources.document_inventory(native_duplicate_key) WHERE native_duplicate_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS source_inventory_queue_idx ON oc_sources.document_inventory(status, modified_at);
CREATE INDEX IF NOT EXISTS source_scan_log_idx ON oc_sources.scan_logs(source_id, started_at DESC);

COMMENT ON SCHEMA oc_sources IS 'Metadata-only source registry. Content extraction and graph mutation are prohibited.';
COMMENT ON COLUMN oc_sources.document_inventory.provenance IS 'Immutable-origin metadata identifying provider and external file ID.';

