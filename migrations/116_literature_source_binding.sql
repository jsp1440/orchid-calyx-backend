-- CALYX-100-L3 / #313
-- Transactional, owner/project-scoped literature -> canonical document binding.
-- Additive only.  Canonical document identities remain owned by
-- oc_document_intelligence; this table records a resolved cross-system binding.

CREATE TABLE IF NOT EXISTS oc_document_intelligence.literature_source_bindings (
    binding_id BIGSERIAL PRIMARY KEY,
    owner_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    paper_id TEXT NOT NULL,
    analysis_id TEXT NOT NULL,
    record_id BIGINT NOT NULL
        REFERENCES oc_document_intelligence.records(record_id),
    source_object_type TEXT NOT NULL,
    source_object_id BIGINT NOT NULL,
    revision_id BIGINT NOT NULL,
    extraction_run_id BIGINT NOT NULL
        REFERENCES oc_document_intelligence.extraction_runs(extraction_run_id),
    source_hash CHAR(64) NOT NULL,
    binding_fingerprint CHAR(64) NOT NULL,
    display_policy TEXT NOT NULL,
    internal_use_permission BOOLEAN NOT NULL DEFAULT FALSE,
    language TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(owner_id, project_id, paper_id, analysis_id),
    UNIQUE(owner_id, project_id, binding_fingerprint)
);

CREATE TABLE IF NOT EXISTS oc_document_intelligence.literature_evidence_bindings (
    binding_id BIGINT NOT NULL
        REFERENCES oc_document_intelligence.literature_source_bindings(binding_id)
        ON DELETE RESTRICT,
    evidence_id TEXT NOT NULL,
    anchor_id BIGINT NOT NULL
        REFERENCES oc_document_intelligence.source_anchors(anchor_id),
    source_hash CHAR(64) NOT NULL,
    excerpt_hash CHAR(64) NOT NULL,
    char_start BIGINT,
    char_end BIGINT,
    section_id TEXT,
    evidence_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(binding_id, evidence_id)
);

CREATE INDEX IF NOT EXISTS literature_binding_source_idx
    ON oc_document_intelligence.literature_source_bindings(record_id, revision_id, extraction_run_id);
CREATE INDEX IF NOT EXISTS literature_binding_scope_idx
    ON oc_document_intelligence.literature_source_bindings(owner_id, project_id, paper_id);
CREATE INDEX IF NOT EXISTS literature_evidence_anchor_idx
    ON oc_document_intelligence.literature_evidence_bindings(anchor_id);

-- Bindings are provenance history.  Application code may append a new analysis
-- binding but must never rewrite or delete a prior binding in place.
CREATE OR REPLACE FUNCTION oc_document_intelligence.reject_literature_binding_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'literature source bindings are immutable';
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'literature_source_bindings_immutable'
    ) THEN
        CREATE TRIGGER literature_source_bindings_immutable
        BEFORE UPDATE OR DELETE ON oc_document_intelligence.literature_source_bindings
        FOR EACH ROW EXECUTE FUNCTION oc_document_intelligence.reject_literature_binding_mutation();
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'literature_evidence_bindings_immutable'
    ) THEN
        CREATE TRIGGER literature_evidence_bindings_immutable
        BEFORE UPDATE OR DELETE ON oc_document_intelligence.literature_evidence_bindings
        FOR EACH ROW EXECUTE FUNCTION oc_document_intelligence.reject_literature_binding_mutation();
    END IF;
END
$$;
