-- BUILD-062 Calyx Queue Schema
-- Creates the oc_admin.build062_calyx_queue table for persisting job state
-- across workers.  Safe to run multiple times (idempotent).

CREATE TABLE IF NOT EXISTS oc_admin.build062_calyx_queue (
    id          TEXT        PRIMARY KEY,
    payload     JSONB       NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- Index by status for filtered list queries
CREATE INDEX IF NOT EXISTS idx_build062_calyx_queue_status
    ON oc_admin.build062_calyx_queue ((payload->>'status'));

-- Index by priority (desc) for ordered queue consumption
CREATE INDEX IF NOT EXISTS idx_build062_calyx_queue_priority
    ON oc_admin.build062_calyx_queue (((payload->>'priority')::int) DESC);

-- Index by queued_at for FIFO ordering within same priority
CREATE INDEX IF NOT EXISTS idx_build062_calyx_queue_queued_at
    ON oc_admin.build062_calyx_queue ((payload->>'queued_at') ASC);
