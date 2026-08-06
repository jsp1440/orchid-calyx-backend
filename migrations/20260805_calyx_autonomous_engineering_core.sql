CREATE TABLE IF NOT EXISTS calyx_engineering_programs (
    program_id VARCHAR(36) PRIMARY KEY,
    owner VARCHAR(240) NOT NULL,
    title VARCHAR(240) NOT NULL,
    objective TEXT NOT NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'draft',
    max_active_jobs INTEGER NOT NULL DEFAULT 6,
    paused BOOLEAN NOT NULL DEFAULT FALSE,
    cancellation_reason TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ NULL,
    CONSTRAINT ck_calyx_program_active_limit CHECK (max_active_jobs BETWEEN 1 AND 6)
);

CREATE INDEX IF NOT EXISTS ix_calyx_engineering_programs_owner ON calyx_engineering_programs(owner);
CREATE INDEX IF NOT EXISTS ix_calyx_engineering_programs_status ON calyx_engineering_programs(status);

CREATE TABLE IF NOT EXISTS calyx_engineering_program_jobs (
    program_job_id VARCHAR(36) PRIMARY KEY,
    program_id VARCHAR(36) NOT NULL REFERENCES calyx_engineering_programs(program_id) ON DELETE CASCADE,
    orchestrator_job_id VARCHAR(36) NULL REFERENCES calyx_orchestrator_jobs(job_id) ON DELETE SET NULL,
    job_key VARCHAR(120) NOT NULL,
    role_key VARCHAR(80) NOT NULL,
    title VARCHAR(240) NOT NULL,
    repository VARCHAR(240) NOT NULL,
    branch VARCHAR(240) NULL,
    mutating BOOLEAN NOT NULL DEFAULT FALSE,
    work_fingerprint VARCHAR(64) NOT NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'waiting',
    outcome VARCHAR(40) NULL,
    evidence_json TEXT NULL,
    blocker TEXT NULL,
    human_action TEXT NULL,
    lease_owner VARCHAR(240) NULL,
    lease_token VARCHAR(36) NULL,
    lease_expires_at TIMESTAMPTZ NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ NULL,
    CONSTRAINT uq_calyx_program_job_key UNIQUE (program_id, job_key),
    CONSTRAINT uq_calyx_program_work_fingerprint UNIQUE (program_id, work_fingerprint)
);

ALTER TABLE calyx_engineering_program_jobs
    ADD COLUMN IF NOT EXISTS lease_owner VARCHAR(240) NULL,
    ADD COLUMN IF NOT EXISTS lease_token VARCHAR(36) NULL,
    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 3;

CREATE INDEX IF NOT EXISTS ix_calyx_program_jobs_program ON calyx_engineering_program_jobs(program_id);
CREATE INDEX IF NOT EXISTS ix_calyx_program_jobs_status ON calyx_engineering_program_jobs(status);
CREATE INDEX IF NOT EXISTS ix_calyx_program_jobs_role ON calyx_engineering_program_jobs(role_key);
CREATE INDEX IF NOT EXISTS ix_calyx_program_jobs_repository_status ON calyx_engineering_program_jobs(repository, status);
CREATE INDEX IF NOT EXISTS ix_calyx_program_jobs_branch_status ON calyx_engineering_program_jobs(branch, status) WHERE branch IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_calyx_program_jobs_orchestrator ON calyx_engineering_program_jobs(orchestrator_job_id) WHERE orchestrator_job_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_calyx_program_jobs_lease ON calyx_engineering_program_jobs(status, lease_expires_at) WHERE status = 'running';
CREATE INDEX IF NOT EXISTS ix_calyx_program_jobs_lease_owner ON calyx_engineering_program_jobs(lease_owner) WHERE lease_owner IS NOT NULL;

CREATE TABLE IF NOT EXISTS calyx_engineering_program_dependencies (
    dependency_id VARCHAR(36) PRIMARY KEY,
    program_id VARCHAR(36) NOT NULL REFERENCES calyx_engineering_programs(program_id) ON DELETE CASCADE,
    upstream_program_job_id VARCHAR(36) NOT NULL REFERENCES calyx_engineering_program_jobs(program_job_id) ON DELETE CASCADE,
    downstream_program_job_id VARCHAR(36) NOT NULL REFERENCES calyx_engineering_program_jobs(program_job_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_calyx_program_dependency UNIQUE (program_id, upstream_program_job_id, downstream_program_job_id),
    CONSTRAINT ck_calyx_program_dependency_not_self CHECK (upstream_program_job_id <> downstream_program_job_id)
);

CREATE INDEX IF NOT EXISTS ix_calyx_program_dependencies_program ON calyx_engineering_program_dependencies(program_id);
CREATE INDEX IF NOT EXISTS ix_calyx_program_dependencies_upstream ON calyx_engineering_program_dependencies(upstream_program_job_id);
CREATE INDEX IF NOT EXISTS ix_calyx_program_dependencies_downstream ON calyx_engineering_program_dependencies(downstream_program_job_id);

COMMENT ON TABLE calyx_engineering_programs IS 'Governed multi-agent engineering programs with bounded concurrency and human safety gates.';
COMMENT ON TABLE calyx_engineering_program_jobs IS 'Authoritative specialized-agent work items belonging to an engineering program.';
COMMENT ON TABLE calyx_engineering_program_dependencies IS 'Directed prerequisite edges controlling automatic downstream job release.';
