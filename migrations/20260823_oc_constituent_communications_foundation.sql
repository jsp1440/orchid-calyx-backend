BEGIN;

CREATE SCHEMA IF NOT EXISTS oc_constituent;
CREATE SCHEMA IF NOT EXISTS oc_communications;

CREATE TABLE IF NOT EXISTS oc_constituent.organizations (
    id BIGSERIAL PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE CHECK (slug = LOWER(slug)),
    display_name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'society'
        CHECK (kind IN ('orchid_continuum', 'society', 'nonprofit', 'institution', 'partner', 'other')),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('pending', 'active', 'suspended', 'closed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_constituent.constituents (
    id BIGSERIAL PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('person', 'organization')),
    display_name TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_constituent.identity_links (
    id BIGSERIAL PRIMARY KEY,
    constituent_id BIGINT NOT NULL
        REFERENCES oc_constituent.constituents(id) ON DELETE RESTRICT,
    auth_subject TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_constituent.email_addresses (
    id BIGSERIAL PRIMARY KEY,
    constituent_id BIGINT NOT NULL
        REFERENCES oc_constituent.constituents(id) ON DELETE RESTRICT,
    organization_id BIGINT
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    normalized_email TEXT NOT NULL CHECK (normalized_email = LOWER(normalized_email)),
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    verification_state TEXT NOT NULL DEFAULT 'unverified'
        CHECK (verification_state IN ('unverified', 'pending', 'verified', 'invalid')),
    verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE NULLS NOT DISTINCT (constituent_id, organization_id, normalized_email),
    CHECK ((verification_state = 'verified') = (verified_at IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_oc_constituent_primary_email_scope
    ON oc_constituent.email_addresses (constituent_id, COALESCE(organization_id, 0))
    WHERE is_primary;

CREATE TABLE IF NOT EXISTS oc_constituent.memberships (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    constituent_id BIGINT NOT NULL
        REFERENCES oc_constituent.constituents(id) ON DELETE RESTRICT,
    level_code TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'active', 'grace', 'lapsed', 'cancelled')),
    starts_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    source_kind TEXT NOT NULL DEFAULT 'manual',
    source_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, constituent_id),
    CHECK (expires_at IS NULL OR starts_at IS NULL OR expires_at >= starts_at)
);

CREATE INDEX IF NOT EXISTS ix_oc_constituent_memberships_org_status
    ON oc_constituent.memberships (organization_id, status);

CREATE TABLE IF NOT EXISTS oc_constituent.communication_preferences (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    constituent_id BIGINT NOT NULL
        REFERENCES oc_constituent.constituents(id) ON DELETE RESTRICT,
    channel TEXT NOT NULL DEFAULT 'email' CHECK (channel IN ('email', 'postal', 'sms')),
    purpose TEXT NOT NULL CHECK (purpose IN (
        'transactional', 'membership_relationship', 'research_delivery', 'community',
        'fundraising', 'marketing', 'support', 'administrative'
    )),
    topic TEXT NOT NULL DEFAULT '*',
    state TEXT NOT NULL CHECK (state IN ('subscribed', 'unsubscribed', 'required_service')),
    source_kind TEXT NOT NULL,
    evidence_ref TEXT,
    supersedes_id BIGINT
        REFERENCES oc_constituent.communication_preferences(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_oc_constituent_preferences_lookup
    ON oc_constituent.communication_preferences (
        constituent_id, organization_id, channel, purpose, topic, created_at DESC
    );

CREATE TABLE IF NOT EXISTS oc_constituent.suppressions (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    constituent_id BIGINT
        REFERENCES oc_constituent.constituents(id) ON DELETE RESTRICT,
    normalized_email TEXT,
    kind TEXT NOT NULL CHECK (kind IN ('unsubscribe', 'hard_bounce', 'complaint', 'invalid', 'admin_block')),
    reason TEXT,
    source_kind TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lifted_at TIMESTAMPTZ,
    CHECK (constituent_id IS NOT NULL OR normalized_email IS NOT NULL),
    CHECK (normalized_email IS NULL OR normalized_email = LOWER(normalized_email))
);

CREATE INDEX IF NOT EXISTS ix_oc_constituent_active_suppressions
    ON oc_constituent.suppressions (organization_id, constituent_id, normalized_email)
    WHERE lifted_at IS NULL;

CREATE TABLE IF NOT EXISTS oc_communications.intents (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    purpose TEXT NOT NULL CHECK (purpose IN (
        'transactional', 'membership_relationship', 'research_delivery', 'community',
        'fundraising', 'marketing', 'support', 'administrative'
    )),
    initiating_module TEXT NOT NULL,
    initiating_principal TEXT NOT NULL,
    subject TEXT NOT NULL,
    template_ref TEXT,
    content_artifact_ref TEXT,
    content_sha256 CHAR(64),
    audience_definition JSONB NOT NULL DEFAULT '{}'::jsonb,
    required_auth_class TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'draft'
        CHECK (state IN (
            'draft', 'awaiting_approval', 'approved', 'sending', 'completed',
            'partially_failed', 'cancelled'
        )),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_oc_communications_intents_org_state
    ON oc_communications.intents (organization_id, state, created_at DESC);

CREATE TABLE IF NOT EXISTS oc_communications.audience_snapshots (
    id BIGSERIAL PRIMARY KEY,
    intent_id BIGINT NOT NULL UNIQUE
        REFERENCES oc_communications.intents(id) ON DELETE RESTRICT,
    audience_sha256 CHAR(64),
    frozen_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((audience_sha256 IS NULL) = (frozen_at IS NULL))
);

CREATE TABLE IF NOT EXISTS oc_communications.audience_members (
    id BIGSERIAL PRIMARY KEY,
    snapshot_id BIGINT NOT NULL
        REFERENCES oc_communications.audience_snapshots(id) ON DELETE RESTRICT,
    constituent_id BIGINT NOT NULL
        REFERENCES oc_constituent.constituents(id) ON DELETE RESTRICT,
    normalized_email TEXT NOT NULL CHECK (normalized_email = LOWER(normalized_email)),
    allowed BOOLEAN NOT NULL,
    decision_reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (snapshot_id, constituent_id, normalized_email)
);

CREATE TABLE IF NOT EXISTS oc_communications.approval_events (
    id BIGSERIAL PRIMARY KEY,
    intent_id BIGINT NOT NULL
        REFERENCES oc_communications.intents(id) ON DELETE RESTRICT,
    action TEXT NOT NULL CHECK (action IN ('approved', 'rejected', 'cancelled')),
    principal TEXT NOT NULL,
    auth_class TEXT NOT NULL,
    audience_sha256 CHAR(64) NOT NULL,
    rationale TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION oc_communications.guard_frozen_audience_member()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    frozen TIMESTAMPTZ;
BEGIN
    SELECT frozen_at INTO frozen
    FROM oc_communications.audience_snapshots
    WHERE id = COALESCE(OLD.snapshot_id, NEW.snapshot_id);

    IF frozen IS NOT NULL THEN
        RAISE EXCEPTION 'FROZEN_AUDIENCE_IMMUTABLE';
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_frozen_audience_member
    ON oc_communications.audience_members;
CREATE TRIGGER trg_guard_frozen_audience_member
BEFORE UPDATE OR DELETE ON oc_communications.audience_members
FOR EACH ROW EXECUTE FUNCTION oc_communications.guard_frozen_audience_member();

CREATE OR REPLACE FUNCTION oc_communications.guard_frozen_snapshot()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.frozen_at IS NOT NULL THEN
        RAISE EXCEPTION 'FROZEN_AUDIENCE_IMMUTABLE';
    END IF;
    IF NEW.frozen_at IS NULL OR NEW.audience_sha256 IS NULL THEN
        RAISE EXCEPTION 'AUDIENCE_FREEZE_REQUIRES_HASH';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_frozen_snapshot
    ON oc_communications.audience_snapshots;
CREATE TRIGGER trg_guard_frozen_snapshot
BEFORE UPDATE ON oc_communications.audience_snapshots
FOR EACH ROW
WHEN (OLD.frozen_at IS DISTINCT FROM NEW.frozen_at OR OLD.audience_sha256 IS DISTINCT FROM NEW.audience_sha256)
EXECUTE FUNCTION oc_communications.guard_frozen_snapshot();

COMMENT ON SCHEMA oc_constituent IS
    'Shared identity-adjacent constituent relationships. Authentication remains external; private scientific/user data does not automatically cross organization boundaries.';
COMMENT ON SCHEMA oc_communications IS
    'Governed communication intents and immutable approved audiences. This schema does not itself grant or execute outbound delivery.';
COMMENT ON COLUMN oc_constituent.identity_links.auth_subject IS
    'Stable external auth subject such as supabase:<uuid>; no password or auth credential is stored here.';
COMMENT ON TABLE oc_constituent.communication_preferences IS
    'Append-oriented preference ledger. New decisions supersede earlier rows rather than erasing consent provenance.';
COMMENT ON TABLE oc_communications.approval_events IS
    'Approval audit record bound to the exact frozen audience hash. Inbound email/content is never an approval principal.';

COMMIT;
