-- CALYX CORE 2B: durable taxonomy review provenance.
-- Additive migration. Does not activate taxonomy or mutate oc_graph.
-- Extends taxonomy_pipeline.review_queue with durable provenance rows
-- so resolved/dismissed review items can carry reviewer identity, rationale,
-- decision hash, and resolution timestamp required for scientific activation.

CREATE SCHEMA IF NOT EXISTS taxonomy_pipeline;

CREATE TABLE IF NOT EXISTS taxonomy_pipeline.taxonomy_review_provenance (
    release_id text NOT NULL,
    review_key text NOT NULL,
    reviewer_id text NOT NULL,
    reviewer_display text,
    rationale text NOT NULL,
    decision_hash text NOT NULL,
    resolved_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (release_id, review_key),
    FOREIGN KEY (release_id, review_key)
        REFERENCES taxonomy_pipeline.review_queue (release_id, review_key)
        ON DELETE RESTRICT,
    CONSTRAINT taxonomy_review_provenance_reviewer_id_nonempty
        CHECK (length(btrim(reviewer_id)) > 0),
    CONSTRAINT taxonomy_review_provenance_rationale_nonempty
        CHECK (length(btrim(rationale)) > 0),
    CONSTRAINT taxonomy_review_provenance_decision_hash_sha256
        CHECK (decision_hash ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_taxonomy_review_provenance_release
    ON taxonomy_pipeline.taxonomy_review_provenance (release_id);

COMMENT ON TABLE taxonomy_pipeline.taxonomy_review_provenance IS
    'Durable scientific review provenance for taxonomy review items. '
    'A row here records a non-empty human reviewer identity and rationale plus '
    'a lowercase SHA-256 decision hash. Runtime activation gating additionally '
    'verifies that digest against the current review evidence/disposition and '
    'rejects stale provenance whose resolution predates the review item update. '
    'Absence, malformed content, stale content, or a digest mismatch cannot '
    'satisfy activation review.';
