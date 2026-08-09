-- CALYX conversation current-main: persistent owner-scoped research conversation sessions.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS research_station;

CREATE TABLE IF NOT EXISTS research_station.conversation_sessions (
    conversation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_subject TEXT NOT NULL,
    project_id UUID REFERENCES research_station.projects(project_id),
    title TEXT NOT NULL DEFAULT 'Calyx conversation'
        CHECK (char_length(title) BETWEEN 1 AND 160),
    active_taxon_id TEXT,
    active_document_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0)
);
CREATE INDEX IF NOT EXISTS idx_rs_conversation_owner_project_updated
    ON research_station.conversation_sessions(owner_subject, project_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS research_station.conversation_messages (
    message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL
        REFERENCES research_station.conversation_sessions(conversation_id),
    owner_subject TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('OPERATOR','CALYX')),
    content TEXT NOT NULL CHECK (char_length(content) BETWEEN 1 AND 50000),
    epistemic_status TEXT,
    context_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_refs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    tool_trace_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    data_status TEXT NOT NULL DEFAULT 'CONVERSATION_CONTEXT'
        CHECK (data_status = 'CONVERSATION_CONTEXT'),
    evidence_authority BOOLEAN NOT NULL DEFAULT FALSE
        CHECK (evidence_authority = FALSE),
    scientific_publication_authorized BOOLEAN NOT NULL DEFAULT FALSE
        CHECK (scientific_publication_authorized = FALSE),
    knowledge_graph_mutation_authorized BOOLEAN NOT NULL DEFAULT FALSE
        CHECK (knowledge_graph_mutation_authorized = FALSE),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_rs_conversation_messages_session_time
    ON research_station.conversation_messages(conversation_id, created_at, message_id);

CREATE OR REPLACE FUNCTION research_station.reject_conversation_message_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Calyx conversation messages are append-only';
END $$;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'rs_conversation_messages_immutable') THEN
        CREATE TRIGGER rs_conversation_messages_immutable
        BEFORE UPDATE OR DELETE ON research_station.conversation_messages
        FOR EACH ROW EXECUTE FUNCTION research_station.reject_conversation_message_mutation();
    END IF;
END $$;

REVOKE ALL ON research_station.conversation_sessions FROM PUBLIC;
REVOKE ALL ON research_station.conversation_messages FROM PUBLIC;
