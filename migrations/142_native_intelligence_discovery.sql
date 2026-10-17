-- Native Global Intelligence Discovery: run ledger, incremental cursors,
-- per-provider discovery records and source-identity verification state.
-- Extends the existing oc_intake intelligence ledger (108/109); it does not
-- create a second scheduler, research database or knowledge graph.
BEGIN;

CREATE SCHEMA IF NOT EXISTS oc_intake;

CREATE TABLE IF NOT EXISTS oc_intake.discovery_runs (
    id BIGSERIAL PRIMARY KEY,
    run_key TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1 CHECK (attempt >= 1),
    mode TEXT NOT NULL CHECK (mode IN ('SCHEDULED','MANUAL','HISTORICAL')),
    status TEXT NOT NULL DEFAULT 'RUNNING'
        CHECK (status IN ('RUNNING','COMPLETED','PARTIAL','NO_WORK','FAILED','INTERRUPTED')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    profiles JSONB NOT NULL DEFAULT '[]'::jsonb,
    budget JSONB NOT NULL DEFAULT '{}'::jsonb,
    usage JSONB NOT NULL DEFAULT '{}'::jsonb,
    counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    provider_results JSONB NOT NULL DEFAULT '[]'::jsonb,
    zero_work_reason TEXT,
    failure_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    discovery_version TEXT NOT NULL,
    external_contact_performed BOOLEAN NOT NULL DEFAULT FALSE CHECK (external_contact_performed = FALSE),
    canonical_mutation_performed BOOLEAN NOT NULL DEFAULT FALSE CHECK (canonical_mutation_performed = FALSE),
    UNIQUE (run_key, attempt),
    -- A cycle that did nothing must say why.
    CHECK (status <> 'NO_WORK' OR zero_work_reason IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS oc_intake.discovery_cursors (
    profile_key TEXT NOT NULL,
    provider TEXT NOT NULL,
    watermark DATE,
    last_run_id BIGINT REFERENCES oc_intake.discovery_runs(id) ON DELETE SET NULL,
    last_success_at TIMESTAMPTZ,
    last_error TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (profile_key, provider)
);

CREATE TABLE IF NOT EXISTS oc_intake.discovery_records (
    id BIGSERIAL PRIMARY KEY,
    intelligence_item_id BIGINT NOT NULL REFERENCES oc_intake.intelligence_items(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    provider_record_id TEXT NOT NULL,
    doi TEXT,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    source_published_on DATE,
    source_date_precision TEXT NOT NULL DEFAULT 'UNKNOWN'
        CHECK (source_date_precision IN ('DAY','MONTH','YEAR','UNKNOWN')),
    first_discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    first_run_id BIGINT REFERENCES oc_intake.discovery_runs(id) ON DELETE SET NULL,
    last_run_id BIGINT REFERENCES oc_intake.discovery_runs(id) ON DELETE SET NULL,
    profile_key TEXT NOT NULL,
    novelty TEXT NOT NULL
        CHECK (novelty IN ('NEW_PUBLICATION','HISTORICAL_RECOVERY','UPDATED','ALREADY_TRACKED')),
    metadata_sha256 CHAR(64) NOT NULL,
    update_count INTEGER NOT NULL DEFAULT 0 CHECK (update_count >= 0),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (provider, provider_record_id)
);

CREATE TABLE IF NOT EXISTS oc_intake.discovery_verification_states (
    intelligence_item_id BIGINT PRIMARY KEY REFERENCES oc_intake.intelligence_items(id) ON DELETE CASCADE,
    verification_state TEXT NOT NULL
        CHECK (verification_state IN ('UNVERIFIED','SOURCE_LOCATED','VERIFIED','PARTIALLY_VERIFIED','CONTRADICTED','UNRESOLVED')),
    basis JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Source identity can be verified automatically; scientific claims cannot.
    claim_verified BOOLEAN NOT NULL DEFAULT FALSE CHECK (claim_verified = FALSE),
    primary_source_attempted_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS discovery_runs_started_idx
    ON oc_intake.discovery_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS discovery_records_item_idx
    ON oc_intake.discovery_records(intelligence_item_id);
CREATE INDEX IF NOT EXISTS discovery_records_doi_idx
    ON oc_intake.discovery_records(doi) WHERE doi IS NOT NULL;
CREATE INDEX IF NOT EXISTS discovery_records_title_idx
    ON oc_intake.discovery_records(normalized_title);
CREATE INDEX IF NOT EXISTS discovery_records_discovered_idx
    ON oc_intake.discovery_records(first_discovered_at DESC);

COMMIT;
