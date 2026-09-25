-- CALYX-EVOLVE-001 experiment ledger.
-- Durable memory for the bounded taxonomy/data-curation experiment loop.
--
-- Apply manually after backup. This migration is idempotent and non-destructive:
-- it only creates the oc_admin schema (if absent) and seven new tables. It reads,
-- alters and drops nothing that already exists, and it touches no taxonomy,
-- Knowledge Graph, occurrence or publication table.
--
-- Rollback: migrations/CALYX-EVOLVE-001-experiment-ledger_rollback.sql
\set ON_ERROR_STOP on

BEGIN;

CREATE SCHEMA IF NOT EXISTS oc_admin;

-- One experiment campaign. Always opens in governance state DRAFT with
-- execution scope STAGING_ONLY; both are carried inside payload and asserted in
-- application code before any run executes.
CREATE TABLE IF NOT EXISTS oc_admin.calyx_evolve_campaigns (
    campaign_id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Versioned cognition inputs (LEARN). Immutable: a changed input is a new
-- content_hash, never an update in place.
CREATE TABLE IF NOT EXISTS oc_admin.calyx_evolve_cognition_items (
    campaign_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (campaign_id, item_id, content_hash)
);

-- Designed candidates and their parent lineage. campaign_id and novelty_key are
-- generated from payload so the deduplication lookup stays a plain indexed read.
CREATE TABLE IF NOT EXISTS oc_admin.calyx_evolve_candidates (
    candidate_id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    campaign_id TEXT GENERATED ALWAYS AS (payload ->> 'campaign_id') STORED,
    novelty_key TEXT GENERATED ALWAYS AS (payload ->> 'novelty_key') STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS calyx_evolve_candidates_campaign_idx
    ON oc_admin.calyx_evolve_candidates (campaign_id);

-- Deduplication index. A refuted candidate keeps its row, so the loop does not
-- re-spend on a strategy it has already evaluated.
CREATE UNIQUE INDEX IF NOT EXISTS calyx_evolve_candidates_novelty_idx
    ON oc_admin.calyx_evolve_candidates (campaign_id, novelty_key);

-- Experiment runs. replay_key is UNIQUE: that constraint is the idempotency
-- guarantee, so a repeated experiment reuses the stored record instead of
-- duplicating work.
CREATE TABLE IF NOT EXISTS oc_admin.calyx_evolve_runs (
    run_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    replay_key TEXT NOT NULL,
    terminal_state TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS calyx_evolve_runs_replay_key_idx
    ON oc_admin.calyx_evolve_runs (replay_key);

CREATE INDEX IF NOT EXISTS calyx_evolve_runs_campaign_idx
    ON oc_admin.calyx_evolve_runs (campaign_id);

-- The complete measured metric vector, one row per metric. A metric that could
-- not be measured is stored with state 'unavailable' and a null value; it is
-- never written as a numeric zero.
CREATE TABLE IF NOT EXISTS oc_admin.calyx_evolve_metrics (
    run_id TEXT NOT NULL,
    metric_key TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, metric_key)
);

-- Analyzer findings: success, failure, counterevidence, uncertainty and
-- missing_evidence. Findings are concise summaries; chain-of-thought and
-- provider transcripts are rejected before they reach this table.
CREATE TABLE IF NOT EXISTS oc_admin.calyx_evolve_findings (
    finding_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    finding_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS calyx_evolve_findings_run_idx
    ON oc_admin.calyx_evolve_findings (run_id);

CREATE INDEX IF NOT EXISTS calyx_evolve_findings_type_idx
    ON oc_admin.calyx_evolve_findings (finding_type);

-- Promotion proposals. state is constrained to review_pending or blocked: this
-- ledger has no approved, activated or published state, and grants no taxonomy
-- activation or Knowledge Graph publication authority.
CREATE TABLE IF NOT EXISTS oc_admin.calyx_evolve_promotion_proposals (
    proposal_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    state TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT calyx_evolve_promotion_state_check
        CHECK (state IN ('review_pending', 'blocked'))
);

CREATE INDEX IF NOT EXISTS calyx_evolve_proposals_campaign_idx
    ON oc_admin.calyx_evolve_promotion_proposals (campaign_id);

COMMIT;
