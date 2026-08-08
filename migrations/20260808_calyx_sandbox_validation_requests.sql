CREATE TABLE IF NOT EXISTS calyx_sandbox_validation_requests (
    request_id VARCHAR(36) PRIMARY KEY,
    owner VARCHAR(240) NOT NULL,
    program_job_id VARCHAR(36) NULL,
    repository VARCHAR(240) NOT NULL,
    branch VARCHAR(240) NOT NULL,
    checkout_commit_sha VARCHAR(40) NOT NULL,
    preset VARCHAR(20) NOT NULL,
    targets_json TEXT NOT NULL,
    timeout_seconds INTEGER NOT NULL,
    request_digest VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(40) NOT NULL DEFAULT 'queued',
    claim_worker VARCHAR(240) NULL,
    claim_token VARCHAR(36) NULL,
    claimed_at TIMESTAMPTZ NULL,
    authorization_id VARCHAR(240) NULL,
    policy_digest VARCHAR(64) NULL,
    evidence_uri TEXT NULL,
    outcome VARCHAR(40) NULL,
    receipt_digest VARCHAR(64) NULL UNIQUE,
    result_json TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ NULL,
    CONSTRAINT ck_calyx_sandbox_timeout CHECK (timeout_seconds BETWEEN 1 AND 120),
    CONSTRAINT ck_calyx_sandbox_status CHECK (status IN ('queued', 'claimed', 'completed', 'blocked'))
);

CREATE INDEX IF NOT EXISTS ix_calyx_sandbox_validation_owner ON calyx_sandbox_validation_requests(owner);
CREATE INDEX IF NOT EXISTS ix_calyx_sandbox_validation_status ON calyx_sandbox_validation_requests(status);
CREATE INDEX IF NOT EXISTS ix_calyx_sandbox_validation_program_job ON calyx_sandbox_validation_requests(program_job_id) WHERE program_job_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_calyx_sandbox_validation_repository_branch ON calyx_sandbox_validation_requests(repository, branch);

COMMENT ON TABLE calyx_sandbox_validation_requests IS
    'Durable request-bound validation work and external-supervisor evidence. The application stores only a supervisor credential verifier, never the bearer token.';
