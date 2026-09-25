-- CALYX-GLOSSARY-001 / #710
-- Additive PostgreSQL persistence contract for governed Scientific Language records.
-- Applying this migration to any production database remains separately owner-gated.
-- Candidate and figure identities/content are immutable; human decisions are appended
-- as review events and grant no automatic scientific publication authority.

BEGIN;

CREATE SCHEMA IF NOT EXISTS oc_scientific_language;

CREATE TABLE IF NOT EXISTS oc_scientific_language.glossary_candidates (
    candidate_id CHAR(64) PRIMARY KEY
        CHECK (candidate_id ~ '^[0-9a-f]{64}$'),
    paper_id TEXT NOT NULL CHECK (btrim(paper_id) <> ''),
    source_hash TEXT NOT NULL CHECK (length(source_hash) BETWEEN 16 AND 256),
    source_term_id TEXT NOT NULL CHECK (btrim(source_term_id) <> ''),
    term TEXT NOT NULL CHECK (btrim(term) <> ''),
    normalized_term TEXT NOT NULL CHECK (btrim(normalized_term) <> ''),
    source_status TEXT NOT NULL CHECK (btrim(source_status) <> ''),
    source_provenance JSONB NOT NULL,
    state TEXT NOT NULL CHECK (state IN (
        'UNRESOLVED','CANDIDATES','AMBIGUOUS','MATCHED_PENDING_REVIEW',
        'REVIEWED_MATCH','NEW_CONCEPT_CANDIDATE','REJECTED'
    )),
    matched_concept_id UUID
        REFERENCES oc_concepts.concepts(concept_id) ON DELETE RESTRICT,
    exact_concept_ids JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(exact_concept_ids) = 'array'),
    resolution_reason TEXT NOT NULL CHECK (btrim(resolution_reason) <> ''),
    review_required BOOLEAN NOT NULL DEFAULT TRUE CHECK (review_required),
    canonical_promotion_authorized BOOLEAN NOT NULL DEFAULT FALSE
        CHECK (NOT canonical_promotion_authorized),
    knowledge_graph_publication_authorized BOOLEAN NOT NULL DEFAULT FALSE
        CHECK (NOT knowledge_graph_publication_authorized),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (paper_id, source_hash, source_term_id, normalized_term)
);

CREATE TABLE IF NOT EXISTS oc_scientific_language.glossary_candidate_reviews (
    review_event_id UUID PRIMARY KEY,
    candidate_id CHAR(64) NOT NULL
        REFERENCES oc_scientific_language.glossary_candidates(candidate_id)
        ON DELETE RESTRICT,
    from_state TEXT NOT NULL CHECK (from_state IN (
        'UNRESOLVED','CANDIDATES','AMBIGUOUS','MATCHED_PENDING_REVIEW',
        'REVIEWED_MATCH','NEW_CONCEPT_CANDIDATE','REJECTED'
    )),
    to_state TEXT NOT NULL CHECK (to_state IN (
        'REVIEWED_MATCH','NEW_CONCEPT_CANDIDATE','REJECTED'
    )),
    actor_subject TEXT NOT NULL CHECK (btrim(actor_subject) <> ''),
    reason TEXT NOT NULL CHECK (btrim(reason) <> ''),
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (from_state <> to_state)
);

CREATE TABLE IF NOT EXISTS oc_scientific_language.figure_requests (
    request_id CHAR(64) PRIMARY KEY
        CHECK (request_id ~ '^[0-9a-f]{64}$'),
    concept_id UUID NOT NULL
        REFERENCES oc_concepts.concepts(concept_id) ON DELETE RESTRICT,
    request_type TEXT NOT NULL CHECK (request_type IN (
        'DIAGRAM','SKETCH','COLOR_ILLUSTRATION','PHOTO_SET','ANIMATION',
        'COMPARISON_PLATE','DISSECTION'
    )),
    production_brief TEXT NOT NULL CHECK (btrim(production_brief) <> ''),
    source_ref TEXT NOT NULL CHECK (btrim(source_ref) <> ''),
    source_hash TEXT NOT NULL CHECK (length(source_hash) BETWEEN 16 AND 256),
    citation TEXT,
    state TEXT NOT NULL DEFAULT 'PENDING_REVIEW'
        CHECK (state IN ('PENDING_REVIEW','APPROVED','REJECTED')),
    review_required BOOLEAN NOT NULL DEFAULT TRUE CHECK (review_required),
    scientific_evidence BOOLEAN NOT NULL DEFAULT FALSE
        CHECK (NOT scientific_evidence),
    figure_approval_authorized BOOLEAN NOT NULL DEFAULT FALSE
        CHECK (NOT figure_approval_authorized),
    canonical_mutation_authorized BOOLEAN NOT NULL DEFAULT FALSE
        CHECK (NOT canonical_mutation_authorized),
    knowledge_graph_publication_authorized BOOLEAN NOT NULL DEFAULT FALSE
        CHECK (NOT knowledge_graph_publication_authorized),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_scientific_language.figure_request_reviews (
    review_event_id UUID PRIMARY KEY,
    request_id CHAR(64) NOT NULL
        REFERENCES oc_scientific_language.figure_requests(request_id)
        ON DELETE RESTRICT,
    from_state TEXT NOT NULL
        CHECK (from_state IN ('PENDING_REVIEW','APPROVED','REJECTED')),
    to_state TEXT NOT NULL CHECK (to_state IN ('APPROVED','REJECTED')),
    actor_subject TEXT NOT NULL CHECK (btrim(actor_subject) <> ''),
    reason TEXT NOT NULL CHECK (btrim(reason) <> ''),
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (from_state <> to_state)
);

CREATE INDEX IF NOT EXISTS idx_scientific_language_candidate_source
    ON oc_scientific_language.glossary_candidates(paper_id, source_hash);
CREATE INDEX IF NOT EXISTS idx_scientific_language_candidate_state
    ON oc_scientific_language.glossary_candidates(state);
CREATE INDEX IF NOT EXISTS idx_scientific_language_candidate_concept
    ON oc_scientific_language.glossary_candidates(matched_concept_id);
CREATE INDEX IF NOT EXISTS idx_scientific_language_figure_concept_state
    ON oc_scientific_language.figure_requests(concept_id, state);
CREATE INDEX IF NOT EXISTS idx_scientific_language_candidate_review
    ON oc_scientific_language.glossary_candidate_reviews(candidate_id, created_at);
CREATE INDEX IF NOT EXISTS idx_scientific_language_figure_review
    ON oc_scientific_language.figure_request_reviews(request_id, created_at);

CREATE OR REPLACE FUNCTION oc_scientific_language.reject_record_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'SCIENTIFIC_LANGUAGE_RECORD_IS_APPEND_ONLY';
END;
$$;

DROP TRIGGER IF EXISTS glossary_candidates_append_only
    ON oc_scientific_language.glossary_candidates;
CREATE TRIGGER glossary_candidates_append_only
    BEFORE UPDATE OR DELETE ON oc_scientific_language.glossary_candidates
    FOR EACH ROW EXECUTE FUNCTION oc_scientific_language.reject_record_mutation();

DROP TRIGGER IF EXISTS glossary_candidate_reviews_append_only
    ON oc_scientific_language.glossary_candidate_reviews;
CREATE TRIGGER glossary_candidate_reviews_append_only
    BEFORE UPDATE OR DELETE ON oc_scientific_language.glossary_candidate_reviews
    FOR EACH ROW EXECUTE FUNCTION oc_scientific_language.reject_record_mutation();

DROP TRIGGER IF EXISTS figure_requests_append_only
    ON oc_scientific_language.figure_requests;
CREATE TRIGGER figure_requests_append_only
    BEFORE UPDATE OR DELETE ON oc_scientific_language.figure_requests
    FOR EACH ROW EXECUTE FUNCTION oc_scientific_language.reject_record_mutation();

DROP TRIGGER IF EXISTS figure_request_reviews_append_only
    ON oc_scientific_language.figure_request_reviews;
CREATE TRIGGER figure_request_reviews_append_only
    BEFORE UPDATE OR DELETE ON oc_scientific_language.figure_request_reviews
    FOR EACH ROW EXECUTE FUNCTION oc_scientific_language.reject_record_mutation();

REVOKE ALL ON oc_scientific_language.glossary_candidates FROM PUBLIC;
REVOKE ALL ON oc_scientific_language.glossary_candidate_reviews FROM PUBLIC;
REVOKE ALL ON oc_scientific_language.figure_requests FROM PUBLIC;
REVOKE ALL ON oc_scientific_language.figure_request_reviews FROM PUBLIC;

COMMIT;
