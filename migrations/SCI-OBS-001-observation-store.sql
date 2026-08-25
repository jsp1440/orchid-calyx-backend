-- SCI-OBS-001 — Scientific Observability append-only store (DRAFT — NOT APPLIED)
--
-- This migration is intentionally NOT wired into alembic/mission control and
-- MUST NOT be applied to any production database as part of SCI-OBS-001. It
-- documents the exact durable shape of the append-only observation store whose
-- reference implementation is app/scientific_observability/store.py.
--
-- Authority boundary: this table stores OBSERVATIONS only. Rows here never
-- authorize taxonomy publication, Knowledge Graph mutation, evidence
-- promotion, or scientific-conclusion publication. Protected locality,
-- credentials, and raw prompt contents are excluded by the redaction pass
-- (app/scientific_observability/redaction.py) before any write.

CREATE TABLE IF NOT EXISTS scientific_observation_events (
    -- Immutable OCID event identity (OC:EVENT:<32 hex>). Idempotency key.
    event_id            TEXT PRIMARY KEY,
    schema_version      TEXT NOT NULL DEFAULT 'sci-obs-event-v1',
    event_type          TEXT NOT NULL,
    occurred_at         TIMESTAMPTZ NOT NULL,
    recorded_at         TIMESTAMPTZ NOT NULL,
    correlation_id      TEXT NOT NULL,
    parent_event_id     TEXT NULL,
    sequence            INTEGER NOT NULL CHECK (sequence >= 1),
    mission_id          TEXT NULL,
    run_id              TEXT NULL,
    request_id          TEXT NULL,
    accepted_name       TEXT NULL,          -- denormalized query key from taxon.accepted_name
    canonical_taxon_id  TEXT NULL,
    pipeline_stage      TEXT NOT NULL,
    safe_status         TEXT NOT NULL,      -- ok|blocked|withheld|refused|degraded|error|unknown
    reason_code         TEXT NULL,
    -- Full redacted envelope (sci-obs-event-v1). No secrets / protected locality.
    payload             JSONB NOT NULL,
    CONSTRAINT recorded_after_occurred CHECK (recorded_at >= occurred_at),
    CONSTRAINT parent_not_self CHECK (parent_event_id IS NULL OR parent_event_id <> event_id)
);

-- Append-only enforcement: block UPDATE and DELETE at the DB layer.
CREATE OR REPLACE FUNCTION scientific_observation_events_append_only()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'scientific_observation_events is append-only (% blocked)', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sci_obs_append_only ON scientific_observation_events;
CREATE TRIGGER trg_sci_obs_append_only
    BEFORE UPDATE OR DELETE ON scientific_observation_events
    FOR EACH ROW EXECUTE FUNCTION scientific_observation_events_append_only();

-- Query keys: keep taxon/source/run/correlation identifiers queryable while
-- high-cardinality free text stays out of the index set.
CREATE INDEX IF NOT EXISTS ix_sci_obs_correlation ON scientific_observation_events (correlation_id, sequence);
CREATE INDEX IF NOT EXISTS ix_sci_obs_type        ON scientific_observation_events (event_type);
CREATE INDEX IF NOT EXISTS ix_sci_obs_accepted    ON scientific_observation_events (accepted_name);
CREATE INDEX IF NOT EXISTS ix_sci_obs_status      ON scientific_observation_events (safe_status);
