-- BUILD-BRAIN-114U follow-on: durable CI repair/revalidation evidence.
-- Additive only. Applying this migration in production is a separate owner-governed action.

CREATE TABLE IF NOT EXISTS calyx_git_proposal_ci_repair_events (
    event_id BIGSERIAL PRIMARY KEY,
    repair_key VARCHAR(64) NOT NULL,
    event_kind VARCHAR(40) NOT NULL,
    source_plan_digest VARCHAR(64) NOT NULL,
    source_receipt_digest VARCHAR(64) NOT NULL,
    repository VARCHAR(240) NOT NULL,
    proposed_branch VARCHAR(240) NOT NULL,
    pull_request_number INTEGER NOT NULL,
    head_sha VARCHAR(40) NOT NULL,
    payload_json TEXT NOT NULL,
    event_digest VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_calyx_ci_repair_key_sha256 CHECK (repair_key ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_calyx_ci_repair_plan_sha256 CHECK (source_plan_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_calyx_ci_repair_receipt_sha256 CHECK (source_receipt_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_calyx_ci_repair_event_sha256 CHECK (event_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_calyx_ci_repair_head_sha CHECK (head_sha ~ '^[0-9a-f]{40}$'),
    CONSTRAINT ck_calyx_ci_repair_pr_positive CHECK (pull_request_number > 0),
    CONSTRAINT ck_calyx_ci_repair_event_kind CHECK (event_kind IN ('assignment', 'revalidation')),
    CONSTRAINT uq_calyx_ci_repair_key_kind UNIQUE (repair_key, event_kind),
    CONSTRAINT uq_calyx_ci_repair_event_digest UNIQUE (event_digest)
);

CREATE INDEX IF NOT EXISTS ix_calyx_ci_repair_plan
    ON calyx_git_proposal_ci_repair_events (source_plan_digest);
CREATE INDEX IF NOT EXISTS ix_calyx_ci_repair_repository_pr
    ON calyx_git_proposal_ci_repair_events (repository, pull_request_number);
CREATE INDEX IF NOT EXISTS ix_calyx_ci_repair_created
    ON calyx_git_proposal_ci_repair_events (created_at DESC);
