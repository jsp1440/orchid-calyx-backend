-- CALYX CORE 2: durable World Plants/Hassler staging only.
-- Additive migration. This schema does not activate taxonomy or mutate oc_graph.

CREATE SCHEMA IF NOT EXISTS taxonomy_pipeline;

CREATE TABLE IF NOT EXISTS taxonomy_pipeline.releases (
    release_id text PRIMARY KEY,
    source_sha256 text NOT NULL UNIQUE,
    version_label text NOT NULL,
    filename text NOT NULL,
    acquired_at text NOT NULL,
    source_encoding text NOT NULL,
    source_row_count integer NOT NULL CHECK (source_row_count >= 0),
    source_payload bytea NOT NULL,
    state text NOT NULL DEFAULT 'inspected'
        CHECK (state IN ('inspected', 'staging', 'staged', 'review_required', 'reviewed')),
    automatic_promotion boolean NOT NULL DEFAULT false CHECK (automatic_promotion = false),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS taxonomy_pipeline.staged_taxa (
    release_id text NOT NULL REFERENCES taxonomy_pipeline.releases(release_id) ON DELETE RESTRICT,
    source_row_number integer NOT NULL,
    taxon_code text NOT NULL,
    world_plants_number text,
    scientific_name text NOT NULL,
    row_checksum text NOT NULL,
    normalized_payload jsonb NOT NULL,
    PRIMARY KEY (release_id, source_row_number)
);

-- Row checksums are intentionally non-unique. The source release can contain
-- byte-identical duplicate taxon rows; both source row numbers must be retained
-- so the review queue can expose the duplication rather than silently discard it.
CREATE INDEX IF NOT EXISTS idx_taxonomy_staged_taxa_checksum
    ON taxonomy_pipeline.staged_taxa (release_id, row_checksum);

CREATE INDEX IF NOT EXISTS idx_taxonomy_staged_taxa_identity
    ON taxonomy_pipeline.staged_taxa (release_id, taxon_code, scientific_name);

CREATE TABLE IF NOT EXISTS taxonomy_pipeline.staging_checkpoints (
    release_id text PRIMARY KEY REFERENCES taxonomy_pipeline.releases(release_id) ON DELETE RESTRICT,
    next_row_index integer NOT NULL DEFAULT 0 CHECK (next_row_index >= 0),
    staged_count integer NOT NULL DEFAULT 0 CHECK (staged_count >= 0),
    completed boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS taxonomy_pipeline.change_reports (
    release_id text PRIMARY KEY REFERENCES taxonomy_pipeline.releases(release_id) ON DELETE RESTRICT,
    baseline_release_id text REFERENCES taxonomy_pipeline.releases(release_id) ON DELETE RESTRICT,
    report jsonb NOT NULL,
    generated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS taxonomy_pipeline.review_queue (
    release_id text NOT NULL REFERENCES taxonomy_pipeline.releases(release_id) ON DELETE RESTRICT,
    review_key text NOT NULL,
    category text NOT NULL,
    summary text NOT NULL,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'dismissed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (release_id, review_key)
);

CREATE INDEX IF NOT EXISTS idx_taxonomy_review_queue_open
    ON taxonomy_pipeline.review_queue (release_id, status, category);
