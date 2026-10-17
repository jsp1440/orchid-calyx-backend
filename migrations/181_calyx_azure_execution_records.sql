-- Optional provider write-ahead evidence only; no queue or execution authority.
-- Apply to non-production only after operator approval. No automatic migration.
CREATE TABLE IF NOT EXISTS calyx_azure_execution_records (
    program_job_id VARCHAR(36) PRIMARY KEY
        REFERENCES calyx_engineering_program_jobs(program_job_id),
    lease_digest VARCHAR(64) NOT NULL,
    input_checksum VARCHAR(64) NOT NULL,
    config_checksum VARCHAR(64) NOT NULL,
    state VARCHAR(40) NOT NULL,
    execution_reference TEXT,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    receipt_json TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
