-- Durable Brain pulse state and receipts (P1 sustained autonomy).
-- Safe to apply repeatedly. ensure_orchestrator_schema creates the same tables
-- with checkfirst for databases that never ran this file. Not applied to
-- production by this change.

CREATE TABLE IF NOT EXISTS calyx_brain_pulse_ledgers (
    ledger_key VARCHAR(120) PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS calyx_brain_pulse_receipts (
    receipt_id VARCHAR(36) PRIMARY KEY,
    ledger_key VARCHAR(120) NOT NULL,
    pulse_id VARCHAR(80) NOT NULL,
    receipt_json TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_calyx_brain_pulse_receipts_ledger_key
    ON calyx_brain_pulse_receipts(ledger_key);
CREATE INDEX IF NOT EXISTS ix_calyx_brain_pulse_receipts_recorded_at
    ON calyx_brain_pulse_receipts(recorded_at);
