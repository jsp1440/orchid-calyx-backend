CREATE SCHEMA IF NOT EXISTS oc_candidate_knowledge;

CREATE TABLE IF NOT EXISTS oc_candidate_knowledge.extraction_runs (
 candidate_run_id BIGSERIAL PRIMARY KEY,
 configuration_hash CHAR(64) NOT NULL,
 extractor_version TEXT NOT NULL,
 ruleset_version TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('PLANNING','PLANNED','EXTRACTING','CANCELLING','CANCELLED','PARTIAL','COMPLETED','FAILED')),
 last_completed_item_id BIGINT,
 cancellation_requested_at TIMESTAMPTZ,
 metrics JSONB NOT NULL DEFAULT '{}',
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS oc_candidate_knowledge.run_items (
 item_id BIGSERIAL PRIMARY KEY,
 candidate_run_id BIGINT NOT NULL REFERENCES oc_candidate_knowledge.extraction_runs(candidate_run_id),
 source_object_type TEXT NOT NULL,
 source_object_id BIGINT NOT NULL,
 revision_id BIGINT NOT NULL REFERENCES oc_import.document_revisions(revision_id),
 extraction_run_id BIGINT NOT NULL REFERENCES oc_document_intelligence.extraction_runs(extraction_run_id),
 evidence_fingerprint CHAR(64) NOT NULL,
 plan_action TEXT NOT NULL,
 state TEXT NOT NULL,
 failure JSONB,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(candidate_run_id, source_object_type, source_object_id, evidence_fingerprint)
);

CREATE TABLE IF NOT EXISTS oc_candidate_knowledge.candidates (
 candidate_id BIGSERIAL PRIMARY KEY,
 candidate_run_id BIGINT NOT NULL REFERENCES oc_candidate_knowledge.extraction_runs(candidate_run_id),
 candidate_kind TEXT NOT NULL,
 normalized_subject TEXT NOT NULL,
 predicate TEXT NOT NULL,
 object_value TEXT,
 numeric_value NUMERIC,
 unit TEXT,
 qualifiers JSONB NOT NULL DEFAULT '{}',
 confidence NUMERIC NOT NULL CHECK(confidence BETWEEN 0 AND 1),
 confidence_components JSONB NOT NULL DEFAULT '{}',
 extraction_method TEXT NOT NULL,
 extractor_version TEXT NOT NULL,
 ruleset_version TEXT NOT NULL,
 candidate_hash CHAR(64) NOT NULL,
 evidence_fingerprint CHAR(64) NOT NULL,
 version INTEGER NOT NULL CHECK(version > 0),
 active BOOLEAN NOT NULL DEFAULT TRUE,
 review_state TEXT NOT NULL DEFAULT 'REQUIRED',
 published BOOLEAN NOT NULL DEFAULT FALSE CHECK(published = FALSE),
 superseded_by_candidate_id BIGINT REFERENCES oc_candidate_knowledge.candidates(candidate_id),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(candidate_hash, evidence_fingerprint, extractor_version, ruleset_version)
);

CREATE TABLE IF NOT EXISTS oc_candidate_knowledge.candidate_evidence (
 evidence_link_id BIGSERIAL PRIMARY KEY,
 candidate_id BIGINT NOT NULL REFERENCES oc_candidate_knowledge.candidates(candidate_id),
 revision_id BIGINT NOT NULL REFERENCES oc_import.document_revisions(revision_id),
 extraction_run_id BIGINT NOT NULL REFERENCES oc_document_intelligence.extraction_runs(extraction_run_id),
 anchor_id BIGINT NOT NULL REFERENCES oc_document_intelligence.source_anchors(anchor_id),
 ordered_span INTEGER NOT NULL,
 exact_locator JSONB NOT NULL,
 authorized_quote TEXT,
 display_policy TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(candidate_id, anchor_id, ordered_span)
);

CREATE TABLE IF NOT EXISTS oc_candidate_knowledge.duplicate_groups (
 duplicate_group_id BIGSERIAL PRIMARY KEY,
 state TEXT NOT NULL DEFAULT 'OPEN',
 rationale TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 resolved_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS oc_candidate_knowledge.duplicate_group_members (
 duplicate_group_id BIGINT NOT NULL REFERENCES oc_candidate_knowledge.duplicate_groups(duplicate_group_id),
 candidate_id BIGINT NOT NULL REFERENCES oc_candidate_knowledge.candidates(candidate_id),
 PRIMARY KEY(duplicate_group_id, candidate_id)
);

CREATE TABLE IF NOT EXISTS oc_candidate_knowledge.conflict_groups (
 conflict_id BIGSERIAL PRIMARY KEY,
 identity JSONB NOT NULL,
 state TEXT NOT NULL DEFAULT 'OPEN',
 resolution JSONB,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 resolved_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS oc_candidate_knowledge.conflict_group_members (
 conflict_id BIGINT NOT NULL REFERENCES oc_candidate_knowledge.conflict_groups(conflict_id),
 candidate_id BIGINT NOT NULL REFERENCES oc_candidate_knowledge.candidates(candidate_id),
 PRIMARY KEY(conflict_id, candidate_id)
);

CREATE TABLE IF NOT EXISTS oc_candidate_knowledge.review_items (
 review_id BIGSERIAL PRIMARY KEY,
 candidate_run_id BIGINT NOT NULL REFERENCES oc_candidate_knowledge.extraction_runs(candidate_run_id),
 candidate_id BIGINT REFERENCES oc_candidate_knowledge.candidates(candidate_id),
 category TEXT NOT NULL,
 severity TEXT NOT NULL,
 evidence JSONB NOT NULL DEFAULT '{}',
 state TEXT NOT NULL DEFAULT 'OPEN',
 decision TEXT,
 rationale TEXT,
 actor TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS oc_candidate_knowledge.audit_events (
 event_id BIGSERIAL PRIMARY KEY,
 candidate_run_id BIGINT REFERENCES oc_candidate_knowledge.extraction_runs(candidate_run_id),
 candidate_id BIGINT REFERENCES oc_candidate_knowledge.candidates(candidate_id),
 event_type TEXT NOT NULL,
 actor TEXT,
 details JSONB NOT NULL DEFAULT '{}',
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS candidate_review_queue_idx ON oc_candidate_knowledge.review_items(state, severity, created_at);
CREATE INDEX IF NOT EXISTS candidate_identity_idx ON oc_candidate_knowledge.candidates(candidate_kind, normalized_subject, predicate, active);
CREATE INDEX IF NOT EXISTS candidate_source_idx ON oc_candidate_knowledge.candidate_evidence(revision_id, extraction_run_id, anchor_id);
