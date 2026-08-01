BEGIN;

DROP INDEX IF EXISTS archive_import_runs_lease_idx;
DROP INDEX IF EXISTS archive_import_runs_status_idx;

UPDATE archive_import_runs
SET status = CASE
    WHEN status = 'queued' THEN 'interrupted'
    WHEN status = 'cancelling' THEN 'interrupted'
    WHEN status = 'cancelled' THEN 'failed'
    ELSE status
END
WHERE status IN ('queued','cancelling','cancelled');

ALTER TABLE archive_import_runs DROP CONSTRAINT IF EXISTS archive_import_runs_status_check;
ALTER TABLE archive_import_runs
    ADD CONSTRAINT archive_import_runs_status_check
    CHECK (status IN ('running','interrupted','completed','failed'));

ALTER TABLE archive_import_runs
    DROP COLUMN IF EXISTS dispatch_reference,
    DROP COLUMN IF EXISTS lease_expires_at,
    DROP COLUMN IF EXISTS lease_owner,
    DROP COLUMN IF EXISTS heartbeat_at,
    DROP COLUMN IF EXISTS attempt_count,
    DROP COLUMN IF EXISTS cancel_requested;

COMMIT;
