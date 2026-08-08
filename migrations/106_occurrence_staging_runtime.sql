BEGIN;

CREATE SCHEMA IF NOT EXISTS occurrence_pipeline;

CREATE TABLE IF NOT EXISTS occurrence_pipeline.staged_occurrences (
    source text NOT NULL,
    source_record_id text NOT NULL,
    scientific_name text NOT NULL,
    accepted_name text,
    taxon_key text,
    canonical_taxon_id text,
    reconciliation_state text NOT NULL,
    latitude double precision,
    longitude double precision,
    country_code text,
    locality text,
    event_date text,
    recorded_by text,
    license text,
    basis_of_record text,
    acquisition_checksum char(16) NOT NULL,
    raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    normalized_payload jsonb NOT NULL,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_record_id),
    UNIQUE (source, acquisition_checksum),
    CHECK (reconciliation_state IN ('resolved','unresolved','review_required','reconciliation_unavailable'))
);

CREATE INDEX IF NOT EXISTS idx_occurrence_pipeline_canonical_taxon
    ON occurrence_pipeline.staged_occurrences(canonical_taxon_id)
    WHERE canonical_taxon_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_occurrence_pipeline_reconciliation
    ON occurrence_pipeline.staged_occurrences(reconciliation_state);

CREATE TABLE IF NOT EXISTS occurrence_pipeline.checkpoints (
    source text NOT NULL,
    job_key text NOT NULL,
    batch_start bigint NOT NULL DEFAULT 0 CHECK (batch_start >= 0),
    batch_end bigint NOT NULL DEFAULT 0 CHECK (batch_end >= batch_start),
    staged_count integer NOT NULL DEFAULT 0 CHECK (staged_count >= 0),
    duplicate_skipped integer NOT NULL DEFAULT 0 CHECK (duplicate_skipped >= 0),
    completed boolean NOT NULL DEFAULT false,
    state jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, job_key)
);

CREATE TABLE IF NOT EXISTS occurrence_pipeline.review_queue (
    source text NOT NULL,
    source_record_id text NOT NULL,
    scientific_name text NOT NULL,
    reason text NOT NULL,
    review_state text NOT NULL,
    suggested_action text NOT NULL,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','dismissed')),
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_record_id)
);

CREATE INDEX IF NOT EXISTS idx_occurrence_review_open
    ON occurrence_pipeline.review_queue(status, review_state);

COMMIT;
