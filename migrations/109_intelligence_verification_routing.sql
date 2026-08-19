BEGIN;

CREATE SCHEMA IF NOT EXISTS oc_intake;

CREATE TABLE IF NOT EXISTS oc_intake.intelligence_verifications (
    id BIGSERIAL PRIMARY KEY,
    intelligence_item_id BIGINT NOT NULL REFERENCES oc_intake.intelligence_items(id) ON DELETE CASCADE,
    source_url TEXT NOT NULL,
    resolved_url TEXT,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('URL','DOI')),
    outcome TEXT NOT NULL CHECK (outcome IN ('SOURCE_CONFIRMED','UNREACHABLE','UNSUPPORTED','NO_SOURCE')),
    http_status INTEGER,
    content_type TEXT,
    source_title TEXT,
    source_doi TEXT,
    published_at TIMESTAMPTZ,
    authority_host TEXT,
    authority_tier TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (authority_tier IN ('PRIMARY','AUTHORITATIVE','SECONDARY','UNKNOWN')),
    evidence_sha256 CHAR(64),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    verifier_version TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    canonical_promotion_performed BOOLEAN NOT NULL DEFAULT FALSE,
    external_contact_performed BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (intelligence_item_id, source_url, evidence_sha256)
);

CREATE TABLE IF NOT EXISTS oc_intake.intelligence_routes (
    id BIGSERIAL PRIMARY KEY,
    intelligence_item_id BIGINT NOT NULL REFERENCES oc_intake.intelligence_items(id) ON DELETE CASCADE,
    destination TEXT NOT NULL,
    route_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (route_status IN ('PENDING','READY','BLOCKED','DELIVERED','REJECTED')),
    rationale TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    requires_human_approval BOOLEAN NOT NULL DEFAULT FALSE,
    canonical_mutation_performed BOOLEAN NOT NULL DEFAULT FALSE,
    external_contact_performed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (intelligence_item_id, destination)
);

CREATE TABLE IF NOT EXISTS oc_intake.intelligence_actions (
    id BIGSERIAL PRIMARY KEY,
    intelligence_item_id BIGINT NOT NULL REFERENCES oc_intake.intelligence_items(id) ON DELETE CASCADE,
    action_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','BLOCKED','WAITING_APPROVAL','COMPLETED','REJECTED')),
    destination TEXT,
    rationale TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    approval_required BOOLEAN NOT NULL DEFAULT FALSE,
    external_side_effect BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (intelligence_item_id, action_type, destination)
);

CREATE INDEX IF NOT EXISTS intelligence_verifications_item_idx
    ON oc_intake.intelligence_verifications(intelligence_item_id, fetched_at DESC);
CREATE INDEX IF NOT EXISTS intelligence_routes_status_idx
    ON oc_intake.intelligence_routes(route_status, destination, updated_at DESC);
CREATE INDEX IF NOT EXISTS intelligence_actions_status_idx
    ON oc_intake.intelligence_actions(status, approval_required, updated_at DESC);

COMMIT;
