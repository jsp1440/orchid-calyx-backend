-- CALYX CORE 2: durable occurrence staging bound to exact taxonomy evidence.
-- Additive staging-only migration. No taxonomy activation or oc_graph mutation.

CREATE SCHEMA IF NOT EXISTS occurrence_pipeline;

CREATE TABLE IF NOT EXISTS occurrence_pipeline.reconciliation_runs (
    run_id text PRIMARY KEY,
    source text NOT NULL CHECK (source IN ('gbif', 'inaturalist')),
    job_key text NOT NULL,
    input_batch_sha256 text NOT NULL CHECK (input_batch_sha256 ~ '^[0-9a-f]{64}$'),
    input_record_count integer NOT NULL CHECK (input_record_count >= 0),
    taxonomy_release_id text NOT NULL REFERENCES taxonomy_pipeline.releases(release_id) ON DELETE RESTRICT,
    taxonomy_source_sha256 text NOT NULL CHECK (taxonomy_source_sha256 ~ '^[0-9a-f]{64}$'),
    taxonomy_review_sha256 text NOT NULL CHECK (taxonomy_review_sha256 ~ '^[0-9a-f]{64}$'),
    taxonomy_open_review_count integer NOT NULL CHECK (taxonomy_open_review_count >= 0),
    taxonomy_context_sha256 text NOT NULL CHECK (taxonomy_context_sha256 ~ '^[0-9a-f]{64}$'),
    schema_version text NOT NULL,
    completed boolean NOT NULL DEFAULT false,
    automatic_promotion boolean NOT NULL DEFAULT false CHECK (automatic_promotion = false),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, job_key, input_batch_sha256, taxonomy_context_sha256)
);

CREATE TABLE IF NOT EXISTS occurrence_pipeline.staged_occurrences (
    run_id text NOT NULL REFERENCES occurrence_pipeline.reconciliation_runs(run_id) ON DELETE RESTRICT,
    source_record_id text NOT NULL,
    scientific_name text NOT NULL,
    accepted_name text,
    provider_taxon_key text,
    supplied_world_plants_number text,
    source_taxonomy_record_id text,
    world_plants_number text,
    source_taxon_rank_code text,
    canonical_taxon_id text,
    reconciliation_state text NOT NULL,
    reconciliation_method text NOT NULL,
    canonical_projection_blocker text,
    latitude double precision,
    longitude double precision,
    coordinate_uncertainty_m double precision,
    country_code text,
    locality text,
    event_date text,
    recorded_by text,
    license text,
    basis_of_record text,
    raw_sha256 text NOT NULL CHECK (raw_sha256 ~ '^[0-9a-f]{64}$'),
    raw_payload jsonb NOT NULL,
    normalized_payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, source_record_id),
    CHECK (
        reconciliation_state <> 'source_matched_canonical_pending'
        OR (source_taxonomy_record_id IS NOT NULL AND canonical_taxon_id IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_occurrence_staged_source_taxonomy
    ON occurrence_pipeline.staged_occurrences (run_id, source_taxonomy_record_id);
CREATE INDEX IF NOT EXISTS idx_occurrence_staged_canonical_taxon
    ON occurrence_pipeline.staged_occurrences (run_id, canonical_taxon_id);
CREATE INDEX IF NOT EXISTS idx_occurrence_staged_reconciliation
    ON occurrence_pipeline.staged_occurrences (run_id, reconciliation_state);

CREATE TABLE IF NOT EXISTS occurrence_pipeline.review_queue (
    run_id text NOT NULL REFERENCES occurrence_pipeline.reconciliation_runs(run_id) ON DELETE RESTRICT,
    source_record_id text NOT NULL,
    scientific_name text NOT NULL,
    reason text NOT NULL,
    reconciliation_state text NOT NULL,
    candidate_source_taxonomy_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'dismissed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, source_record_id, reason)
);

CREATE INDEX IF NOT EXISTS idx_occurrence_review_open
    ON occurrence_pipeline.review_queue (run_id, status, reconciliation_state);

CREATE TABLE IF NOT EXISTS occurrence_pipeline.checkpoints (
    run_id text PRIMARY KEY REFERENCES occurrence_pipeline.reconciliation_runs(run_id) ON DELETE RESTRICT,
    next_record_index integer NOT NULL DEFAULT 0 CHECK (next_record_index >= 0),
    staged_count integer NOT NULL DEFAULT 0 CHECK (staged_count >= 0),
    review_count integer NOT NULL DEFAULT 0 CHECK (review_count >= 0),
    duplicate_skipped integer NOT NULL DEFAULT 0 CHECK (duplicate_skipped >= 0),
    completed boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now()
);
