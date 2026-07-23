-- BUILD-RS-001: additive persistent Research Station workspace foundation.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS research_station;

CREATE TABLE IF NOT EXISTS research_station.projects (
    project_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_subject TEXT NOT NULL,
    title TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 160),
    description TEXT NOT NULL DEFAULT '' CHECK (char_length(description) <= 10000),
    research_question TEXT CHECK (char_length(research_question) <= 5000),
    hypothesis TEXT CHECK (char_length(hypothesis) <= 5000),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','PAUSED','COMPLETED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0)
);
CREATE INDEX IF NOT EXISTS idx_rs_projects_owner_archive_updated
    ON research_station.projects(owner_subject, archived_at, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_rs_projects_owner_status
    ON research_station.projects(owner_subject, status);

CREATE TABLE IF NOT EXISTS research_station.saved_searches (
    saved_search_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES research_station.projects(project_id),
    owner_subject TEXT NOT NULL,
    name TEXT NOT NULL CHECK (char_length(name) BETWEEN 1 AND 160),
    query_json JSONB NOT NULL,
    result_count_snapshot INTEGER CHECK (result_count_snapshot >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_rs_saved_search_name
    ON research_station.saved_searches(project_id, lower(name)) WHERE archived_at IS NULL;

CREATE TABLE IF NOT EXISTS research_station.notes (
    note_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES research_station.projects(project_id),
    owner_subject TEXT NOT NULL,
    title TEXT CHECK (char_length(title) <= 200),
    body TEXT NOT NULL CHECK (char_length(body) BETWEEN 1 AND 50000),
    note_type TEXT NOT NULL DEFAULT 'GENERAL'
        CHECK (note_type IN ('GENERAL','QUESTION','METHOD','OBSERVATION')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0)
);
CREATE INDEX IF NOT EXISTS idx_rs_notes_project_updated
    ON research_station.notes(project_id, archived_at, updated_at DESC);

CREATE TABLE IF NOT EXISTS research_station.project_taxa (
    project_id UUID NOT NULL REFERENCES research_station.projects(project_id),
    taxon_id TEXT NOT NULL,
    relationship TEXT NOT NULL DEFAULT 'SUBJECT'
        CHECK (relationship IN ('SUBJECT','COMPARISON','CONTEXT','EXCLUDED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by_subject TEXT NOT NULL,
    PRIMARY KEY(project_id, taxon_id)
);
CREATE TABLE IF NOT EXISTS research_station.project_documents (
    project_id UUID NOT NULL REFERENCES research_station.projects(project_id),
    document_id TEXT NOT NULL,
    revision_id TEXT,
    relationship TEXT NOT NULL DEFAULT 'SOURCE'
        CHECK (relationship IN ('SOURCE','BACKGROUND','METHOD','CONTRADICTS')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by_subject TEXT NOT NULL,
    PRIMARY KEY(project_id, document_id)
);
CREATE TABLE IF NOT EXISTS research_station.project_evidence (
    project_id UUID NOT NULL REFERENCES research_station.projects(project_id),
    evidence_kind TEXT NOT NULL CHECK (evidence_kind IN ('CANDIDATE','AGGREGATE')),
    evidence_id TEXT NOT NULL,
    relationship TEXT NOT NULL DEFAULT 'SUPPORTS'
        CHECK (relationship IN ('SUPPORTS','CONTRADICTS','CONTEXT','REVIEW')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by_subject TEXT NOT NULL,
    PRIMARY KEY(project_id, evidence_kind, evidence_id)
);
CREATE INDEX IF NOT EXISTS idx_rs_project_taxa_id ON research_station.project_taxa(taxon_id);
CREATE INDEX IF NOT EXISTS idx_rs_project_documents_id ON research_station.project_documents(document_id);
CREATE INDEX IF NOT EXISTS idx_rs_project_evidence_id ON research_station.project_evidence(evidence_kind, evidence_id);

CREATE TABLE IF NOT EXISTS research_station.audit_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES research_station.projects(project_id),
    actor_subject TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    request_correlation_id TEXT,
    change_summary JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_rs_audit_project_time
    ON research_station.audit_events(project_id, occurred_at DESC, event_id);

CREATE OR REPLACE FUNCTION research_station.reject_audit_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'research workspace audit events are append-only';
END $$;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'rs_audit_immutable') THEN
        CREATE TRIGGER rs_audit_immutable
        BEFORE UPDATE OR DELETE ON research_station.audit_events
        FOR EACH ROW EXECUTE FUNCTION research_station.reject_audit_mutation();
    END IF;
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA research_station FROM PUBLIC;
