-- CALYX-AUTO-001: durable validator feedback and Brain completion writeback.
-- Additive only. This migration does not enable the persistent worker.

CREATE TABLE IF NOT EXISTS calyx_program_validation_events (
    validation_event_id VARCHAR(36) PRIMARY KEY,
    program_job_id VARCHAR(36) NOT NULL REFERENCES calyx_engineering_program_jobs(program_job_id) ON DELETE CASCADE,
    attempt_count INTEGER NOT NULL CHECK (attempt_count >= 1),
    disposition VARCHAR(40) NOT NULL CHECK (disposition IN ('accept','retry','review_required','dead_letter')),
    code VARCHAR(160) NOT NULL,
    feedback_json TEXT NOT NULL DEFAULT '[]',
    receipt_checksum VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT calyx_program_validation_receipt_sha CHECK (receipt_checksum IS NULL OR receipt_checksum ~ '^[0-9a-f]{64}$')
);
CREATE INDEX IF NOT EXISTS idx_calyx_program_validation_job_created
    ON calyx_program_validation_events(program_job_id, created_at DESC);

CREATE TABLE IF NOT EXISTS calyx_brain_completion_writebacks (
    writeback_id VARCHAR(36) PRIMARY KEY,
    program_id VARCHAR(36) NOT NULL REFERENCES calyx_engineering_programs(program_id) ON DELETE CASCADE,
    program_job_id VARCHAR(36) NOT NULL REFERENCES calyx_engineering_program_jobs(program_job_id) ON DELETE CASCADE,
    owner VARCHAR(240) NOT NULL,
    completion_key VARCHAR(64) NOT NULL,
    payload_json TEXT NOT NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'recorded' CHECK (status IN ('recorded')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    committed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_calyx_brain_writeback_program_job UNIQUE (program_job_id),
    CONSTRAINT uq_calyx_brain_writeback_completion_key UNIQUE (completion_key),
    CONSTRAINT calyx_brain_completion_key_sha CHECK (completion_key ~ '^[0-9a-f]{64}$')
);
CREATE INDEX IF NOT EXISTS idx_calyx_brain_writeback_owner_created
    ON calyx_brain_completion_writebacks(owner, created_at DESC);
