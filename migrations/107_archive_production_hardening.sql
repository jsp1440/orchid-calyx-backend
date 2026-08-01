BEGIN;

ALTER TABLE archive_import_runs
    ADD COLUMN IF NOT EXISTS cancel_requested boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS attempt_count integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS heartbeat_at timestamptz,
    ADD COLUMN IF NOT EXISTS lease_owner text,
    ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz,
    ADD COLUMN IF NOT EXISTS dispatch_reference text;

ALTER TABLE archive_import_runs DROP CONSTRAINT IF EXISTS archive_import_runs_status_check;
ALTER TABLE archive_import_runs
    ADD CONSTRAINT archive_import_runs_status_check
    CHECK (status IN ('queued','running','cancelling','cancelled','interrupted','completed','failed'));

CREATE INDEX IF NOT EXISTS archive_import_runs_status_idx
    ON archive_import_runs(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS archive_import_runs_lease_idx
    ON archive_import_runs(lease_expires_at)
    WHERE status IN ('queued','running','cancelling');

COMMIT;
