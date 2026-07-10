CREATE SCHEMA IF NOT EXISTS oc_admin;

CREATE TABLE IF NOT EXISTS oc_admin.harvester_registry (
    harvester_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    scientific_purpose TEXT NOT NULL,
    connector_source_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    target JSONB NOT NULL DEFAULT '{}'::jsonb,
    query_scope TEXT,
    schedule TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    operational_state TEXT NOT NULL DEFAULT 'active'
        CHECK (operational_state IN ('active','paused','run_once','draining','exhausted','needs_review','redirect_pending','failed','retired')),
    checkpoint_cursor TEXT,
    last_attempted_run TIMESTAMPTZ,
    last_successful_run TIMESTAMPTZ,
    next_scheduled_run TIMESTAMPTZ,
    rows_examined BIGINT,
    rows_inserted BIGINT,
    rows_updated BIGINT,
    duplicates_detected BIGINT,
    rows_rejected BIGINT,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    run_duration_ms BIGINT,
    estimated_cost NUMERIC,
    freshness TEXT,
    novelty_yield_rate NUMERIC,
    source_exhaustion_score NUMERIC,
    downstream_relationships_created BIGINT,
    current_recommendation TEXT,
    recommendation_rationale TEXT,
    required_approval_level TEXT NOT NULL DEFAULT 'owner',
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_admin.harvester_runs (
    run_id TEXT PRIMARY KEY,
    harvester_id TEXT NOT NULL REFERENCES oc_admin.harvester_registry(harvester_id),
    starting_checkpoint TEXT,
    ending_checkpoint TEXT,
    trigger_type TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    records_examined BIGINT,
    inserted BIGINT,
    updated BIGINT,
    duplicated BIGINT,
    rejected BIGINT,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    novelty_rate NUMERIC,
    relationship_yield BIGINT,
    source_response_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    execution_log_reference TEXT,
    decision_approval_reference TEXT,
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_admin.harvester_target_proposals (
    proposal_id TEXT PRIMARY KEY,
    harvester_id TEXT NOT NULL REFERENCES oc_admin.harvester_registry(harvester_id),
    current_assignment JSONB NOT NULL,
    proposed_assignment JSONB NOT NULL,
    scientific_rationale TEXT NOT NULL,
    evidence_considered JSONB NOT NULL DEFAULT '[]'::jsonb,
    expected_value TEXT,
    confidence NUMERIC,
    risk_level TEXT NOT NULL,
    approval_requirement TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    decision_reference TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_harvester_runs_harvester_started
    ON oc_admin.harvester_runs (harvester_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_harvester_registry_operational_state
    ON oc_admin.harvester_registry (operational_state);

INSERT INTO oc_admin.harvester_registry
    (harvester_id, display_name, scientific_purpose, connector_source_id, source_type, target, query_scope, schedule, provenance)
VALUES
    ('inaturalist', 'iNaturalist', 'Occurrence and community media freshness', 'inat', 'observations', '{"target_type":"taxon","target_value":"Orchidaceae"}', 'orchid observations and usable media', 'daily', '{"source":"BUILD-049 idempotent seed","historical_telemetry":"unknown"}'),
    ('gbif', 'GBIF', 'Occurrence backbone and range evidence', 'gbif', 'occurrences', '{"target_type":"taxon","target_value":"Orchidaceae"}', 'occurrence backbone, coordinates, dates', 'daily', '{"source":"BUILD-049 idempotent seed","historical_telemetry":"unknown"}'),
    ('world_plants_hassler', 'World Plants / Hassler', 'Taxonomic synonym and accepted-name backbone', 'world-plants', 'taxonomy', '{"target_type":"taxon","target_value":"Orchidaceae"}', 'taxonomic backbone reconciliation', 'weekly', '{"source":"BUILD-049 idempotent seed","historical_telemetry":"unknown"}'),
    ('eol_traitbank', 'EOL / TraitBank', 'Trait and ecology evidence', 'eol-traitbank', 'traits', '{"target_type":"evidence_type","target_value":"traits"}', 'trait and ecology records', 'weekly', '{"source":"BUILD-049 idempotent seed","historical_telemetry":"unknown"}'),
    ('image_media', 'Image/media harvesters', 'Species and genus media coverage', 'media', 'images', '{"target_type":"image_media_gap","target_value":"species pages without media"}', 'image/media gap coverage', 'daily', '{"source":"BUILD-049 idempotent seed","historical_telemetry":"unknown"}'),
    ('literature', 'Literature harvesters', 'Citation-backed relationship extraction', 'literature', 'literature', '{"target_type":"literature_topic","target_value":"orchid ecology relationships"}', 'literature query and citation extraction', 'weekly', '{"source":"BUILD-049 idempotent seed","historical_telemetry":"unknown"}'),
    ('mycorrhizal_data', 'Mycorrhizal harvesters', 'Orchid-fungal relationship coverage', 'mycorrhiza', 'relationships', '{"target_type":"relationship_gap_query","target_value":"orchid mycorrhizal gaps"}', 'fungal relationship evidence', 'weekly', '{"source":"BUILD-049 idempotent seed","historical_telemetry":"unknown"}'),
    ('climate_elevation', 'Climate/elevation enrichment', 'Climate and elevation context enrichment', 'climate', 'enrichment', '{"target_type":"elevation_band","target_value":"unknown"}', 'climate and elevation enrichment', 'weekly', '{"source":"BUILD-049 idempotent seed","historical_telemetry":"unknown"}'),
    ('conservation_status', 'Conservation enrichment', 'Conservation status and threat context', 'conservation', 'enrichment', '{"target_type":"conservation_status_gap","target_value":"unknown"}', 'conservation gap enrichment', 'weekly', '{"source":"BUILD-049 idempotent seed","historical_telemetry":"unknown"}')
ON CONFLICT (harvester_id) DO NOTHING;
