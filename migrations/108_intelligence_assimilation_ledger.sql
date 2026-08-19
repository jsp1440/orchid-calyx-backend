BEGIN;

CREATE SCHEMA IF NOT EXISTS oc_intake;

CREATE TABLE IF NOT EXISTS oc_intake.intelligence_items (
    id BIGSERIAL PRIMARY KEY,
    knowledge_fingerprint CHAR(64) NOT NULL UNIQUE,
    domain TEXT NOT NULL,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    current_detail TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL DEFAULT 'MEDIUM'
        CHECK (priority IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    lifecycle TEXT NOT NULL DEFAULT 'DISCOVERED'
        CHECK (lifecycle IN ('DISCOVERED','VERIFIED','COMPARED','ROUTED','ASSIMILATED','ACTIONED','REJECTED','DUPLICATE','CONFLICT','NEEDS_REVIEW')),
    knowledge_delta TEXT NOT NULL DEFAULT 'UNASSESSED'
        CHECK (knowledge_delta IN ('UNASSESSED','ALREADY_KNOWN','NEW_EVIDENCE','CONFLICT','NEW_ENTITY','NEW_RELATIONSHIP','NEW_SOURCE','CAPABILITY_GAP','REQUIRES_REVIEW')),
    verification_required BOOLEAN NOT NULL DEFAULT TRUE,
    canonical_destinations JSONB NOT NULL DEFAULT '[]'::jsonb,
    follow_up_tasks JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
    dois JSONB NOT NULL DEFAULT '[]'::jsonb,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_verified_at TIMESTAMPTZ,
    last_compared_at TIMESTAMPTZ,
    routed_at TIMESTAMPTZ,
    assimilated_at TIMESTAMPTZ,
    actioned_at TIMESTAMPTZ,
    observation_count INTEGER NOT NULL DEFAULT 0 CHECK (observation_count >= 0),
    canonical_promotion_prohibited BOOLEAN NOT NULL DEFAULT TRUE,
    external_contact_prohibited BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_intake.intelligence_observations (
    id BIGSERIAL PRIMARY KEY,
    intelligence_item_id BIGINT NOT NULL REFERENCES oc_intake.intelligence_items(id) ON DELETE CASCADE,
    source_id BIGINT NOT NULL REFERENCES oc_intake.sources(id) ON DELETE CASCADE,
    observation_fingerprint CHAR(64) NOT NULL UNIQUE,
    sender TEXT,
    message_id TEXT,
    observed_title TEXT NOT NULL,
    observed_detail TEXT NOT NULL DEFAULT '',
    observed_priority TEXT NOT NULL DEFAULT 'MEDIUM'
        CHECK (observed_priority IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    source_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
    dois JSONB NOT NULL DEFAULT '[]'::jsonb,
    parser_version TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (source_id, intelligence_item_id)
);

CREATE TABLE IF NOT EXISTS oc_intake.intelligence_events (
    id BIGSERIAL PRIMARY KEY,
    intelligence_item_id BIGINT NOT NULL REFERENCES oc_intake.intelligence_items(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    previous_state JSONB,
    resulting_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT,
    actor TEXT,
    origin TEXT NOT NULL DEFAULT 'AUTOMATED' CHECK (origin IN ('AUTOMATED','HUMAN')),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS intelligence_items_lifecycle_idx
    ON oc_intake.intelligence_items(lifecycle, knowledge_delta, priority, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS intelligence_items_domain_idx
    ON oc_intake.intelligence_items(domain, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS intelligence_observations_item_idx
    ON oc_intake.intelligence_observations(intelligence_item_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS intelligence_observations_source_idx
    ON oc_intake.intelligence_observations(source_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS intelligence_events_item_idx
    ON oc_intake.intelligence_events(intelligence_item_id, occurred_at DESC);

COMMIT;
