BEGIN;

CREATE SCHEMA IF NOT EXISTS oc_concepts;

CREATE TABLE IF NOT EXISTS oc_concepts.glossary_candidates (
    candidate_id uuid PRIMARY KEY,
    fingerprint text NOT NULL UNIQUE,
    display_term text NOT NULL,
    normalized_term text NOT NULL,
    language text NOT NULL DEFAULT 'und',
    source_kind text NOT NULL,
    source_hash text NOT NULL,
    source_locator jsonb NOT NULL DEFAULT '{}'::jsonb,
    char_start integer,
    char_end integer,
    resolution_state text NOT NULL CHECK (resolution_state IN (
        'UNRESOLVED', 'CANDIDATES', 'AMBIGUOUS', 'MATCHED_PENDING_REVIEW',
        'REVIEWED_MATCH', 'NEW_CONCEPT_CANDIDATE', 'REJECTED'
    )),
    matched_concept_id uuid REFERENCES oc_concepts.concepts(concept_id),
    proposed_definition text,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    review_state text NOT NULL DEFAULT 'PENDING',
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((char_start IS NULL AND char_end IS NULL) OR
           (char_start IS NOT NULL AND char_end IS NOT NULL AND char_start >= 0 AND char_end >= char_start))
);

CREATE INDEX IF NOT EXISTS idx_glossary_candidates_normalized_term
    ON oc_concepts.glossary_candidates(normalized_term);
CREATE INDEX IF NOT EXISTS idx_glossary_candidates_resolution_state
    ON oc_concepts.glossary_candidates(resolution_state, review_state);
CREATE INDEX IF NOT EXISTS idx_glossary_candidates_matched_concept
    ON oc_concepts.glossary_candidates(matched_concept_id)
    WHERE matched_concept_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS oc_concepts.glossary_figure_requests (
    request_id uuid PRIMARY KEY,
    fingerprint text NOT NULL UNIQUE,
    concept_id uuid NOT NULL REFERENCES oc_concepts.concepts(concept_id),
    request_type text NOT NULL CHECK (request_type IN (
        'DIAGRAM', 'SKETCH', 'COLOR_ILLUSTRATION', 'PHOTO_SET',
        'ANIMATION', 'COMPARISON_PLATE', 'DISSECTION'
    )),
    title text NOT NULL,
    caption text,
    generation_prompt text NOT NULL,
    priority integer NOT NULL DEFAULT 50 CHECK (priority BETWEEN 0 AND 100),
    status text NOT NULL DEFAULT 'REQUESTED' CHECK (status IN (
        'REQUESTED', 'IN_PROGRESS', 'READY_FOR_REVIEW', 'APPROVED', 'REJECTED', 'SUPERSEDED'
    )),
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    review_required boolean NOT NULL DEFAULT true,
    scientific_evidence boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    revised_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_glossary_figure_requests_queue
    ON oc_concepts.glossary_figure_requests(status, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_glossary_figure_requests_concept
    ON oc_concepts.glossary_figure_requests(concept_id, status);

COMMIT;
