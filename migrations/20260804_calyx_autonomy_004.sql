ALTER TABLE calyx_orchestrator_jobs
    ADD COLUMN IF NOT EXISTS policy_class VARCHAR(40) NOT NULL DEFAULT 'read_only_research',
    ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS deadline_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS ix_calyx_jobs_policy_status
    ON calyx_orchestrator_jobs(policy_class, status, priority, created_at);

CREATE INDEX IF NOT EXISTS ix_calyx_jobs_retry_ready
    ON calyx_orchestrator_jobs(status, next_attempt_at, priority)
    WHERE status = 'queued';

COMMENT ON COLUMN calyx_orchestrator_jobs.policy_class IS
    'Governed autonomy class: read_only_research, candidate_generation, review_required, or owner_only.';
COMMENT ON COLUMN calyx_orchestrator_jobs.next_attempt_at IS
    'Earliest time a queued retry may be claimed; null means immediately eligible.';
COMMENT ON COLUMN calyx_orchestrator_jobs.deadline_at IS
    'Optional deadline after which a job may not be newly claimed.';
