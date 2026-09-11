-- SCIENTIFIC-MEMORY-MVP-001
-- Additive only. Applying this migration remains a separately governed action.

CREATE SCHEMA IF NOT EXISTS research_station;

CREATE TABLE IF NOT EXISTS research_station.scientific_memory_captures (
    capture_id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES research_station.projects(project_id),
    saved_search_id UUID NOT NULL REFERENCES research_station.saved_searches(saved_search_id),
    owner_subject TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('OASIS','CALYX','RESEARCH_STATION')),
    conversation_id TEXT,
    query_text TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(project_id, fingerprint)
);

CREATE TABLE IF NOT EXISTS research_station.scientific_memory_items (
    memory_item_id UUID PRIMARY KEY,
    capture_id UUID NOT NULL REFERENCES research_station.scientific_memory_captures(capture_id),
    project_id UUID NOT NULL REFERENCES research_station.projects(project_id),
    item_type TEXT NOT NULL CHECK (item_type IN (
        'EVIDENCE','CLAIM','RELATIONSHIP','TRAIT','METHOD','MATERIAL','PROTOCOL',
        'MEASUREMENT','TAXON_MAPPING','CONTRADICTION','UNCERTAINTY','ANALYSIS'
    )),
    authority TEXT NOT NULL CHECK (authority IN (
        'SOURCE_EVIDENCE','CANDIDATE_KNOWLEDGE','CALYX_INFERENCE','RESEARCH_CONTEXT'
    )),
    statement TEXT NOT NULL,
    confidence DOUBLE PRECISION,
    document_id TEXT,
    revision_id TEXT,
    source_identifier TEXT,
    source_locator JSONB NOT NULL DEFAULT '{}'::jsonb,
    authorized_excerpt TEXT,
    rights_basis TEXT NOT NULL CHECK (rights_basis IN (
        'OPEN_ACCESS','AUTHORIZED','USER_PROVIDED','METADATA_ONLY'
    )),
    structured_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    correction_of_item_id UUID REFERENCES research_station.scientific_memory_items(memory_item_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CHECK (
        authority <> 'SOURCE_EVIDENCE'
        OR (document_id IS NOT NULL AND revision_id IS NOT NULL AND source_locator <> '{}'::jsonb)
    )
);

CREATE TABLE IF NOT EXISTS research_station.scientific_memory_decisions (
    decision_id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES research_station.projects(project_id),
    memory_item_id UUID NOT NULL REFERENCES research_station.scientific_memory_items(memory_item_id),
    action TEXT NOT NULL CHECK (action IN ('ACCEPT_REVIEW','REJECT','INVALIDATE','CORRECT')),
    actor_subject TEXT NOT NULL,
    reason TEXT NOT NULL,
    replacement_item_id UUID REFERENCES research_station.scientific_memory_items(memory_item_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((action = 'CORRECT') = (replacement_item_id IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_rs_memory_capture_project_time
    ON research_station.scientific_memory_captures(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_rs_memory_item_project_type
    ON research_station.scientific_memory_items(project_id, item_type);
CREATE INDEX IF NOT EXISTS idx_rs_memory_decision_item_time
    ON research_station.scientific_memory_decisions(memory_item_id, created_at);

CREATE OR REPLACE FUNCTION research_station.reject_scientific_memory_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'SCIENTIFIC_MEMORY_IS_APPEND_ONLY';
END;
$$;

DROP TRIGGER IF EXISTS scientific_memory_items_append_only
    ON research_station.scientific_memory_items;
CREATE TRIGGER scientific_memory_items_append_only
    BEFORE UPDATE OR DELETE ON research_station.scientific_memory_items
    FOR EACH ROW EXECUTE FUNCTION research_station.reject_scientific_memory_mutation();

DROP TRIGGER IF EXISTS scientific_memory_decisions_append_only
    ON research_station.scientific_memory_decisions;
CREATE TRIGGER scientific_memory_decisions_append_only
    BEFORE UPDATE OR DELETE ON research_station.scientific_memory_decisions
    FOR EACH ROW EXECUTE FUNCTION research_station.reject_scientific_memory_mutation();

REVOKE ALL ON research_station.scientific_memory_captures FROM PUBLIC;
REVOKE ALL ON research_station.scientific_memory_items FROM PUBLIC;
REVOKE ALL ON research_station.scientific_memory_decisions FROM PUBLIC;
