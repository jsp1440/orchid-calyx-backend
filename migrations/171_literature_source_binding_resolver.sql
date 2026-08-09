CREATE TABLE IF NOT EXISTS oc_document_intelligence.literature_source_bindings (
    binding_id BIGSERIAL PRIMARY KEY,
    paper_id TEXT NOT NULL,
    analysis_id TEXT NOT NULL,
    source_sha256 CHAR(64) NOT NULL,
    record_id BIGINT NOT NULL REFERENCES oc_document_intelligence.records(record_id),
    revision_id BIGINT NOT NULL REFERENCES oc_import.document_revisions(revision_id),
    extraction_run_id BIGINT NOT NULL REFERENCES oc_document_intelligence.extraction_runs(extraction_run_id),
    binding_fingerprint CHAR(64) NOT NULL,
    binding_method TEXT NOT NULL DEFAULT 'EXACT_HASH_AND_SPAN',
    confidence NUMERIC NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
    actor TEXT NOT NULL,
    tenant_id TEXT,
    project_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (paper_id, analysis_id),
    UNIQUE (binding_fingerprint)
);

CREATE TABLE IF NOT EXISTS oc_document_intelligence.literature_evidence_bindings (
    evidence_binding_id BIGSERIAL PRIMARY KEY,
    binding_id BIGINT NOT NULL REFERENCES oc_document_intelligence.literature_source_bindings(binding_id),
    evidence_id TEXT NOT NULL,
    anchor_id BIGINT NOT NULL REFERENCES oc_document_intelligence.source_anchors(anchor_id),
    char_start BIGINT NOT NULL,
    char_end BIGINT NOT NULL,
    source_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (char_start >= 0),
    CHECK (char_end >= char_start),
    UNIQUE (binding_id, evidence_id)
);

CREATE INDEX IF NOT EXISTS literature_source_binding_record_idx
    ON oc_document_intelligence.literature_source_bindings(record_id, extraction_run_id);
CREATE INDEX IF NOT EXISTS literature_evidence_binding_anchor_idx
    ON oc_document_intelligence.literature_evidence_bindings(anchor_id);

REVOKE UPDATE, DELETE ON oc_document_intelligence.literature_source_bindings FROM PUBLIC;
REVOKE UPDATE, DELETE ON oc_document_intelligence.literature_evidence_bindings FROM PUBLIC;
