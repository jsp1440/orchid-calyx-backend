BEGIN;

CREATE TABLE IF NOT EXISTS calyx_specialist_missions (
    mission_id VARCHAR(36) PRIMARY KEY,
    owner VARCHAR(240) NOT NULL,
    idempotency_key VARCHAR(160) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    kind VARCHAR(80) NOT NULL,
    question TEXT NOT NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'active',
    scientific BOOLEAN NOT NULL DEFAULT TRUE,
    publication_candidate BOOLEAN NOT NULL DEFAULT FALSE,
    automatic_publication BOOLEAN NOT NULL DEFAULT FALSE,
    owner_approval_required BOOLEAN NOT NULL DEFAULT FALSE,
    max_specialists INTEGER NOT NULL DEFAULT 4,
    token_budget INTEGER NOT NULL DEFAULT 100000,
    cost_budget_microusd INTEGER NOT NULL DEFAULT 0,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    cost_used_microusd INTEGER NOT NULL DEFAULT 0,
    activation_json TEXT NOT NULL,
    constraints_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_specialist_mission_owner_idempotency UNIQUE (owner, idempotency_key),
    CONSTRAINT specialist_mission_no_auto_publish CHECK (automatic_publication = FALSE)
);

CREATE TABLE IF NOT EXISTS calyx_specialist_artifacts (
    artifact_id VARCHAR(36) PRIMARY KEY,
    mission_id VARCHAR(36) NOT NULL REFERENCES calyx_specialist_missions(mission_id) ON DELETE CASCADE,
    artifact_key VARCHAR(160) NOT NULL,
    specialist_id VARCHAR(80) NOT NULL,
    artifact_type VARCHAR(80) NOT NULL,
    content_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    cost_microusd INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_specialist_artifact_mission_key UNIQUE (mission_id, artifact_key)
);

CREATE TABLE IF NOT EXISTS calyx_specialist_reviews (
    review_id VARCHAR(36) PRIMARY KEY,
    mission_id VARCHAR(36) NOT NULL REFERENCES calyx_specialist_missions(mission_id) ON DELETE CASCADE,
    review_key VARCHAR(160) NOT NULL,
    reviewer_id VARCHAR(80) NOT NULL DEFAULT 'scientific-reviewer',
    passed BOOLEAN NOT NULL,
    findings_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_specialist_review_mission_key UNIQUE (mission_id, review_key),
    CONSTRAINT specialist_review_independence CHECK (reviewer_id = 'scientific-reviewer')
);

CREATE TABLE IF NOT EXISTS calyx_specialist_approvals (
    approval_id VARCHAR(36) PRIMARY KEY,
    mission_id VARCHAR(36) NOT NULL REFERENCES calyx_specialist_missions(mission_id) ON DELETE CASCADE,
    approval_key VARCHAR(160) NOT NULL,
    actor VARCHAR(240) NOT NULL,
    decision VARCHAR(20) NOT NULL,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_specialist_approval_mission_key UNIQUE (mission_id, approval_key),
    CONSTRAINT specialist_approval_decision CHECK (decision IN ('approved', 'rejected'))
);

CREATE INDEX IF NOT EXISTS ix_specialist_missions_owner_status
    ON calyx_specialist_missions(owner, status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_specialist_artifacts_mission
    ON calyx_specialist_artifacts(mission_id, created_at);
CREATE INDEX IF NOT EXISTS ix_specialist_reviews_mission
    ON calyx_specialist_reviews(mission_id, created_at);
CREATE INDEX IF NOT EXISTS ix_specialist_approvals_mission
    ON calyx_specialist_approvals(mission_id, created_at);

COMMIT;
