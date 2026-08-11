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
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_taxonomy_review_provenance_release
    ON taxonomy_pipeline.taxonomy_review_provenance (release_id);

COMMENT ON TABLE taxonomy_pipeline.taxonomy_review_provenance IS
    'Durable scientific review provenance for taxonomy review items. '
    'A row here indicates a human reviewer provided identity, rationale, '
    'and a verifiable decision hash. Absence of a row means no durable '
    'provenance exists and the item cannot satisfy activation review.';
