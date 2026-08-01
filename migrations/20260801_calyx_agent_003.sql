CREATE TABLE IF NOT EXISTS calyx_orchestrator_jobs (
    job_id VARCHAR(36) PRIMARY KEY,
    job_type VARCHAR(80) NOT NULL,
    title VARCHAR(240) NOT NULL,
    request_text TEXT NOT NULL,
    owner VARCHAR(240) NOT NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 100,
    dependency_job_id VARCHAR(36) NULL REFERENCES calyx_orchestrator_jobs(job_id),
    approval_required BOOLEAN NOT NULL DEFAULT FALSE,
    approval_class VARCHAR(40) NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    lease_owner VARCHAR(160) NULL,
    lease_token VARCHAR(36) NULL,
    lease_expires_at TIMESTAMPTZ NULL,
    result_json TEXT NULL,
    error_code VARCHAR(160) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ NULL
);
CREATE INDEX IF NOT EXISTS ix_calyx_jobs_status_priority ON calyx_orchestrator_jobs(status, priority, created_at);
CREATE INDEX IF NOT EXISTS ix_calyx_jobs_owner ON calyx_orchestrator_jobs(owner);

CREATE TABLE IF NOT EXISTS calyx_orchestrator_findings (
    finding_id VARCHAR(36) PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL REFERENCES calyx_orchestrator_jobs(job_id),
    fingerprint VARCHAR(64) NOT NULL UNIQUE,
    subsystem VARCHAR(120) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    title VARCHAR(240) NOT NULL,
    summary TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    confidence INTEGER NOT NULL DEFAULT 80,
    status VARCHAR(40) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_calyx_findings_status ON calyx_orchestrator_findings(status, severity, updated_at);
