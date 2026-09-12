-- CALYX-RECOVERY-001 (DRAFT — not applied by this branch)
--
-- Authoritative Research Station state. Before this table, projects,
-- questions, claims and evidence lived only as JSON under
-- CALYX_RESEARCH_STATION_DIR, defaulting to /tmp/calyx/research-station, and
-- were lost on any restart that recycled /tmp without anything reporting the
-- loss.
--
-- One table of JSON records rather than a schema per record kind: the record
-- shapes are owned by runtime/research_station.py and versioned there by
-- RESEARCH_SCHEMA_VERSION, and duplicating them here would create a second
-- definition to keep in step.
--
-- project_id carries the BUILD-051 request identity for executor-created
-- projects, so a request and its research workspace share one key.

CREATE SCHEMA IF NOT EXISTS oc_admin;

CREATE TABLE IF NOT EXISTS oc_admin.research_station_records (
    owner_key   text        NOT NULL,
    project_id  text        NOT NULL,
    kind        text        NOT NULL,
    record_id   text        NOT NULL,
    payload     jsonb       NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT NOW(),
    updated_at  timestamptz NOT NULL DEFAULT NOW(),
    PRIMARY KEY (owner_key, project_id, kind, record_id)
);

-- Listing a project's records of one kind is the read the service performs on
-- every cold start.
CREATE INDEX IF NOT EXISTS research_station_records_project_kind_idx
    ON oc_admin.research_station_records (owner_key, project_id, kind);
