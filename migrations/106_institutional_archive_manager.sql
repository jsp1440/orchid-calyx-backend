BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS archive_import_runs (
    id uuid PRIMARY KEY,
    source_path text NOT NULL,
    status text NOT NULL CHECK (status IN ('running','interrupted','completed','failed')),
    options jsonb NOT NULL DEFAULT '{}'::jsonb,
    files_discovered bigint NOT NULL DEFAULT 0,
    files_processed bigint NOT NULL DEFAULT 0,
    duplicates_skipped bigint NOT NULL DEFAULT 0,
    documents_indexed bigint NOT NULL DEFAULT 0,
    entities_extracted bigint NOT NULL DEFAULT 0,
    relationships_created bigint NOT NULL DEFAULT 0,
    error_count bigint NOT NULL DEFAULT 0,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);

CREATE TABLE IF NOT EXISTS archive_documents (
    id uuid PRIMARY KEY,
    canonical_title text NOT NULL,
    extracted_text text NOT NULL DEFAULT '',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS archive_files (
    id uuid PRIMARY KEY,
    document_id uuid REFERENCES archive_documents(id) ON DELETE SET NULL,
    import_run_id uuid NOT NULL REFERENCES archive_import_runs(id) ON DELETE RESTRICT,
    relative_path text NOT NULL,
    sha256 char(64) NOT NULL,
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    media_type text,
    extraction_method text NOT NULL,
    status text NOT NULL,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (sha256)
);

CREATE TABLE IF NOT EXISTS archive_entities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES archive_documents(id) ON DELETE CASCADE,
    label text NOT NULL,
    entity_type text NOT NULL,
    start_offset integer,
    end_offset integer,
    confidence double precision,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS archive_relationships (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES archive_documents(id) ON DELETE CASCADE,
    subject_entity_id uuid REFERENCES archive_entities(id) ON DELETE SET NULL,
    object_entity_id uuid REFERENCES archive_entities(id) ON DELETE SET NULL,
    subject_label text NOT NULL,
    predicate text NOT NULL,
    object_label text NOT NULL,
    confidence double precision,
    evidence_text text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS archive_provenance (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid REFERENCES archive_documents(id) ON DELETE CASCADE,
    file_id uuid REFERENCES archive_files(id) ON DELETE CASCADE,
    import_run_id uuid NOT NULL REFERENCES archive_import_runs(id) ON DELETE RESTRICT,
    event_type text NOT NULL,
    source_uri text,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS archive_checkpoints (
    import_run_id uuid PRIMARY KEY REFERENCES archive_import_runs(id) ON DELETE CASCADE,
    next_file_index bigint NOT NULL DEFAULT 0,
    last_relative_path text,
    state jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS archive_files_run_idx ON archive_files(import_run_id);
CREATE INDEX IF NOT EXISTS archive_files_document_idx ON archive_files(document_id);
CREATE INDEX IF NOT EXISTS archive_documents_created_idx ON archive_documents(created_at DESC);
CREATE INDEX IF NOT EXISTS archive_entities_document_idx ON archive_entities(document_id);
CREATE INDEX IF NOT EXISTS archive_entities_label_idx ON archive_entities(lower(label));
CREATE INDEX IF NOT EXISTS archive_relationships_document_idx ON archive_relationships(document_id);
CREATE INDEX IF NOT EXISTS archive_relationships_predicate_idx ON archive_relationships(predicate);
CREATE INDEX IF NOT EXISTS archive_provenance_run_idx ON archive_provenance(import_run_id);

COMMIT;
