BEGIN;
CREATE SCHEMA IF NOT EXISTS oc_intake;

CREATE TABLE IF NOT EXISTS oc_intake.sources (
    id BIGSERIAL PRIMARY KEY,
    source_type TEXT NOT NULL CHECK (source_type IN ('text','url','file','email','api')),
    title TEXT NOT NULL,
    source_url TEXT,
    raw_content TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    imported_by TEXT,
    status TEXT NOT NULL CHECK (status IN ('NEW','PARSED','REVIEW','APPROVED','PUBLISHED','REJECTED')),
    parser_version TEXT NOT NULL,
    reviewed_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS oc_intake.entities (
    id BIGSERIAL PRIMARY KEY,
    source_id BIGINT NOT NULL REFERENCES oc_intake.sources(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    exact_text TEXT NOT NULL,
    existing_node_id BIGINT,
    proposed_node_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'DRAFT',
    UNIQUE (source_id, entity_type, normalized_name)
);

CREATE TABLE IF NOT EXISTS oc_intake.relationships (
    id BIGSERIAL PRIMARY KEY,
    source_id BIGINT NOT NULL REFERENCES oc_intake.sources(id) ON DELETE CASCADE,
    subject_name TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_name TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    evidence_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT'
);

CREATE TABLE IF NOT EXISTS oc_intake.tasks (
    id BIGSERIAL PRIMARY KEY,
    source_id BIGINT NOT NULL REFERENCES oc_intake.sources(id) ON DELETE CASCADE,
    task_type TEXT NOT NULL,
    title TEXT NOT NULL,
    priority TEXT NOT NULL CHECK (priority IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    rationale TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN'
);

CREATE TABLE IF NOT EXISTS oc_intake.review_queue (
    id BIGSERIAL PRIMARY KEY,
    source_id BIGINT NOT NULL UNIQUE REFERENCES oc_intake.sources(id) ON DELETE CASCADE,
    reviewer TEXT,
    review_status TEXT NOT NULL CHECK (review_status IN ('PENDING','APPROVED','REJECTED','PUBLISHED')),
    review_notes TEXT,
    reviewed_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS intake_sources_status_idx ON oc_intake.sources(status, imported_at DESC);
CREATE INDEX IF NOT EXISTS intake_entities_lookup_idx ON oc_intake.entities(entity_type, normalized_name);
CREATE INDEX IF NOT EXISTS intake_tasks_status_idx ON oc_intake.tasks(status, priority);
COMMIT;
