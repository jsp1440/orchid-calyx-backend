-- Durable receipts for scheduled program-autonomy cycles (one row per cycle).
-- Append-only; safe to apply repeatedly. ensure_orchestrator_schema creates the
-- same table with checkfirst for databases that never ran this file.

CREATE TABLE IF NOT EXISTS calyx_program_autonomy_cycles (
    cycle_id VARCHAR(36) PRIMARY KEY,
    owner VARCHAR(240) NOT NULL,
    worker_id VARCHAR(240) NOT NULL,
    sequence INTEGER NOT NULL,
    poll_seconds INTEGER NOT NULL,
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NOT NULL,
    productive BOOLEAN NOT NULL DEFAULT FALSE,
    category VARCHAR(40) NULL,
    healthy BOOLEAN NOT NULL DEFAULT FALSE,
    completed_jobs INTEGER NOT NULL DEFAULT 0,
    productive_jobs INTEGER NOT NULL DEFAULT 0,
    failed_jobs INTEGER NOT NULL DEFAULT 0,
    reason_code VARCHAR(160) NULL,
    job_keys_json TEXT NOT NULL DEFAULT '[]',
    replenishment_json TEXT NULL,
    deployment_commit VARCHAR(64) NULL
);

CREATE INDEX IF NOT EXISTS ix_calyx_program_autonomy_cycles_owner
    ON calyx_program_autonomy_cycles(owner);
CREATE INDEX IF NOT EXISTS ix_calyx_program_autonomy_cycles_worker_id
    ON calyx_program_autonomy_cycles(worker_id);
CREATE INDEX IF NOT EXISTS ix_calyx_program_autonomy_cycles_finished_at
    ON calyx_program_autonomy_cycles(finished_at);
CREATE INDEX IF NOT EXISTS ix_calyx_program_autonomy_cycles_productive
    ON calyx_program_autonomy_cycles(productive);
