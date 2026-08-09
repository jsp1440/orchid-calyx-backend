CREATE TABLE IF NOT EXISTS oc_concepts.glossary_candidates (
    candidate_id VARCHAR(64) PRIMARY KEY,
    term TEXT NOT NULL,
    normalized_term TEXT NOT NULL,
    language VARCHAR(35) NOT NULL DEFAULT 'und',
    source_uri TEXT NOT NULL,
    source_revision_id TEXT NOT NULL,
    source_checksum VARCHAR(64) NOT NULL,
    evidence_span_id TEXT NOT NULL,
    resolution_state VARCHAR(40) NOT NULL,
    matched_concept_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    reviewed_concept_id UUID NULL REFERENCES oc_concepts.concepts(concept_id),
    reviewed_by TEXT NULL,
    review_rationale TEXT NULL,
    reviewed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revised_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_glossary_candidate_state CHECK (
        resolution_state IN (
            'UNRESOLVED', 'CANDIDATES', 'AMBIGUOUS', 'MATCHED_PENDING_REVIEW',
            'REVIEWED_MATCH', 'NEW_CONCEPT_CANDIDATE', 'REJECTED'
        )
    )
);

CREATE INDEX IF NOT EXISTS ix_glossary_candidates_state
    ON oc_concepts.glossary_candidates(resolution_state, created_at);
CREATE INDEX IF NOT EXISTS ix_glossary_candidates_normalized_term
    ON oc_concepts.glossary_candidates(normalized_term);

CREATE TABLE IF NOT EXISTS oc_concepts.glossary_figure_requests (
    request_id VARCHAR(64) PRIMARY KEY,
    concept_id UUID NOT NULL REFERENCES oc_concepts.concepts(concept_id),
    request_type VARCHAR(40) NOT NULL,
    audience TEXT NOT NULL,
    purpose TEXT NOT NULL,
    source_candidate_id VARCHAR(64) NULL REFERENCES oc_concepts.glossary_candidates(candidate_id),
    review_state VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revised_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_glossary_figure_type CHECK (
        request_type IN (
            'DIAGRAM', 'SKETCH', 'COLOR_ILLUSTRATION', 'PHOTO_SET',
            'ANIMATION', 'COMPARISON_PLATE', 'DISSECTION'
        )
    )
);

CREATE INDEX IF NOT EXISTS ix_glossary_figure_requests_concept
    ON oc_concepts.glossary_figure_requests(concept_id, created_at);

COMMENT ON TABLE oc_concepts.glossary_candidates IS
    'Governed literature-derived scientific vocabulary candidates. Never canonical by insertion alone.';
COMMENT ON TABLE oc_concepts.glossary_figure_requests IS
    'Human-review figure production queue linked to canonical concepts; figure requests are not scientific evidence.';
