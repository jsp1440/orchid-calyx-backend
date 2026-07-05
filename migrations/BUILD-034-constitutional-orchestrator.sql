-- BUILD-034 — Constitutional Mission Orchestrator
-- Persistent schema foundation for delegated Calyx autonomy.

CREATE SCHEMA IF NOT EXISTS oc_governance;

CREATE TABLE IF NOT EXISTS oc_governance.missions (
    id BIGSERIAL PRIMARY KEY,
    mission_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    purpose TEXT NOT NULL,
    success_criteria JSONB NOT NULL DEFAULT '[]'::jsonb,
    safe_autonomy_level INTEGER NOT NULL DEFAULT 0,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_governance.policies (
    id BIGSERIAL PRIMARY KEY,
    policy_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    principle TEXT NOT NULL,
    max_autonomy_level INTEGER NOT NULL DEFAULT 0,
    requires_rollback BOOLEAN NOT NULL DEFAULT TRUE,
    requires_provenance BOOLEAN NOT NULL DEFAULT TRUE,
    protected BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_governance.decision_ledger (
    id BIGSERIAL PRIMARY KEY,
    decision_id TEXT NOT NULL UNIQUE,
    mission_id TEXT NOT NULL,
    action TEXT NOT NULL,
    requested_autonomy_level INTEGER NOT NULL,
    approved_autonomy_level INTEGER NOT NULL,
    status TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    confidence NUMERIC(4,3) NOT NULL DEFAULT 0,
    constitutional_policies JSONB NOT NULL DEFAULT '[]'::jsonb,
    rationale TEXT NOT NULL,
    rollback_checkpoint TEXT,
    governance_question_id TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_governance.governance_questions (
    id BIGSERIAL PRIMARY KEY,
    question_id TEXT NOT NULL UNIQUE,
    mission_id TEXT NOT NULL,
    question TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    answer TEXT,
    precedent_key TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    answered_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS oc_governance.checkpoints (
    id BIGSERIAL PRIMARY KEY,
    checkpoint_id TEXT NOT NULL UNIQUE,
    mission_id TEXT NOT NULL,
    decision_id TEXT,
    checkpoint_type TEXT NOT NULL DEFAULT 'logical',
    rollback_notes TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON SCHEMA oc_governance IS 'Constitutional autonomy, mission governance, decision ledgers, questions, and rollback checkpoints for Calyx.';
COMMENT ON TABLE oc_governance.decision_ledger IS 'Traceable institutional decision records for Calyx mission actions.';
COMMENT ON TABLE oc_governance.governance_questions IS 'Questions created when Calyx reaches the edge of delegated authority.';
