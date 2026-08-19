-- PHASE-2-GITHUB-EXECUTOR-001B
-- Durable asynchronous coding-agent dispatch state.
-- Additive only. Does not activate a worker, credential, merge, or deployment path.

CREATE TABLE IF NOT EXISTS calyx_github_agent_dispatches (
    dispatch_id BIGSERIAL PRIMARY KEY,
    program_job_id VARCHAR(128) NOT NULL,
    mission_id VARCHAR(160) NOT NULL,
    repository VARCHAR(256) NOT NULL,
    base_sha VARCHAR(40) NOT NULL,
    provider VARCHAR(128) NOT NULL,
    issue_number INTEGER NOT NULL,
    state VARCHAR(64) NOT NULL,
    pull_request_number INTEGER NULL,
    pull_request_url VARCHAR(1024) NULL,
    head_sha VARCHAR(40) NULL,
    repair_attempts INTEGER NOT NULL DEFAULT 0,
    last_failure_class VARCHAR(256) NULL,
    snapshot_json TEXT NOT NULL,
    CONSTRAINT uq_calyx_github_agent_dispatch_program_job UNIQUE (program_job_id),
    CONSTRAINT ck_calyx_github_agent_dispatch_issue_positive CHECK (issue_number > 0),
    CONSTRAINT ck_calyx_github_agent_dispatch_pr_positive CHECK (
        pull_request_number IS NULL OR pull_request_number > 0
    ),
    CONSTRAINT ck_calyx_github_agent_dispatch_repair_nonnegative CHECK (repair_attempts >= 0)
);

CREATE INDEX IF NOT EXISTS ix_calyx_github_agent_dispatch_mission
    ON calyx_github_agent_dispatches (mission_id);

CREATE INDEX IF NOT EXISTS ix_calyx_github_agent_dispatch_repository
    ON calyx_github_agent_dispatches (repository);

CREATE INDEX IF NOT EXISTS ix_calyx_github_agent_dispatch_state
    ON calyx_github_agent_dispatches (state);
