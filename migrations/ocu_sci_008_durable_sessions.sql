CREATE SCHEMA IF NOT EXISTS oc_university;

CREATE TABLE IF NOT EXISTS oc_university.lab_sessions (
    session_id UUID PRIMARY KEY,
    laboratory_id TEXT NOT NULL CHECK (laboratory_id LIKE 'OCU-LAB-%'),
    chapter_id TEXT NOT NULL CHECK (chapter_id LIKE 'BITB-CHAPTER-%'),
    learner_actor TEXT NOT NULL CHECK (length(trim(learner_actor)) > 0),
    status TEXT NOT NULL CHECK (status IN (
        'created','observing','questioning','investigating','analyzing',
        'interpreting','communicating','submitted','under_review',
        'changes_requested','approved_for_learning','archived'
    )),
    current_stage TEXT NOT NULL CHECK (current_stage IN (
        'observe','question','investigate','analyze','interpret','communicate','contribute'
    )),
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
    publication_allowed BOOLEAN NOT NULL DEFAULT FALSE CHECK (publication_allowed = FALSE),
    automatic_candidate_knowledge BOOLEAN NOT NULL DEFAULT FALSE CHECK (automatic_candidate_knowledge = FALSE),
    human_review_required BOOLEAN NOT NULL DEFAULT TRUE CHECK (human_review_required = TRUE),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS university_lab_sessions_actor_idx
    ON oc_university.lab_sessions (learner_actor, updated_at DESC);
CREATE INDEX IF NOT EXISTS university_lab_sessions_status_idx
    ON oc_university.lab_sessions (status, updated_at DESC);

CREATE TABLE IF NOT EXISTS oc_university.session_events (
    event_id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES oc_university.lab_sessions(session_id) ON DELETE CASCADE,
    sequence_no BIGINT NOT NULL CHECK (sequence_no > 0),
    event_type TEXT NOT NULL CHECK (event_type IN (
        'observation_added','question_set','hypothesis_added','evidence_examined',
        'analysis_recorded','interpretation_recorded','conclusion_drafted',
        'uncertainty_recorded','stage_advanced','session_submitted'
    )),
    stage TEXT NOT NULL CHECK (stage IN (
        'observe','question','investigate','analyze','interpret','communicate','contribute'
    )),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    actor TEXT NOT NULL CHECK (length(trim(actor)) > 0),
    session_revision BIGINT NOT NULL CHECK (session_revision > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (session_id, sequence_no),
    UNIQUE (session_id, session_revision)
);

CREATE INDEX IF NOT EXISTS university_session_events_session_idx
    ON oc_university.session_events (session_id, sequence_no);

CREATE TABLE IF NOT EXISTS oc_university.session_reviews (
    review_id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES oc_university.lab_sessions(session_id) ON DELETE CASCADE,
    reviewer_actor TEXT NOT NULL CHECK (length(trim(reviewer_actor)) > 0),
    reviewer_capability TEXT NOT NULL CHECK (
        reviewer_capability IN ('review.science','review.expert','review.publish')
    ),
    reviewer_roles JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(reviewer_roles) = 'array'),
    reviewer_qualifications JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(reviewer_qualifications) = 'array'),
    decision TEXT NOT NULL CHECK (decision IN (
        'changes_requested','approved_for_learning','approved_for_candidate_knowledge_consideration'
    )),
    notes TEXT,
    reviewed_revision BIGINT NOT NULL CHECK (reviewed_revision > 0),
    candidate_knowledge_promoted BOOLEAN NOT NULL DEFAULT FALSE CHECK (candidate_knowledge_promoted = FALSE),
    publication_performed BOOLEAN NOT NULL DEFAULT FALSE CHECK (publication_performed = FALSE),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (session_id, reviewed_revision, reviewer_actor)
);

CREATE INDEX IF NOT EXISTS university_session_reviews_session_idx
    ON oc_university.session_reviews (session_id, created_at DESC);

COMMENT ON SCHEMA oc_university IS
    'Orchid Continuum University learner-session persistence. OCU-SCI-008 adds schema only; runtime wiring remains disabled.';
COMMENT ON TABLE oc_university.lab_sessions IS
    'Durable scientific-inquiry sessions. Publication and automatic Candidate Knowledge promotion are structurally prohibited.';
COMMENT ON TABLE oc_university.session_reviews IS
    'Qualified human review decisions with authorization provenance. Candidate Knowledge consideration is not promotion.';
