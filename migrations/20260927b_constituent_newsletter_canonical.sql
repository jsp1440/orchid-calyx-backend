-- Canonical newsletter / contact persistence for the public constituent API (#1652).
--
-- Idempotent. Apply after:
--   migrations/20260823_oc_constituent_communications_foundation.sql
--   migrations/20260926_society_crm_p0_core.sql
--   migrations/20260927_society_crm_p1_tenant_isolation.sql
--
-- The public newsletter/contact API (app/constituent_platform/canonical_store.py)
-- stores its records in the canonical CRM schemas instead of the generic Research
-- Station record store. Everything here is owned by one organization -- the
-- Orchid Continuum platform organization (slug 'orchid-continuum', kind
-- 'orchid_continuum'), which the application creates idempotently -- and every
-- runtime read/write happens under the oc_crm_runtime role with a transaction-local
-- tenant (app/constituent_platform/tenant_db.py).
--
-- Where state lives:
--   * subscribe/unsubscribe state: the existing append-only
--     oc_constituent.communication_preferences ledger (channel 'email', purpose
--     'community', topic '*'); each change supersedes the previous row;
--   * unsubscribe: an active oc_constituent.suppressions row of kind 'unsubscribe'
--     (lifted_at set on re-subscribe; critical kinds are never lifted by the API);
--   * topics/cadence/format and the stable public constituent id:
--     oc_communications.newsletter_subscription_settings (this file);
--   * the held welcome email: an oc_communications.intents row with a frozen
--     single-member audience snapshot, state 'awaiting_approval';
--   * published issues: oc_communications.newsletter_issues (this file);
--   * contact intake: oc_communications.inbound_contact_messages (this file).
--
-- This migration creates no organization, constituent, or message rows.

BEGIN;

DO $$
BEGIN
    IF to_regprocedure('oc_constituent.current_tenant_id()') IS NULL
       OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'oc_crm_runtime')
       OR NOT EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'oc_constituent' AND table_name = 'constituents'
             AND column_name = 'owner_organization_id'
       ) THEN
        RAISE EXCEPTION 'OC_NEWSLETTER_CANONICAL_REQUIRES_P1: apply migrations/20260927_society_crm_p1_tenant_isolation.sql first';
    END IF;
END
$$;

-- Session-temporary idempotent constraint helper (same posture as P1: legacy rows
-- that cannot satisfy a new constraint leave it NOT VALID, still enforced for every
-- new or updated row).
CREATE OR REPLACE FUNCTION pg_temp.oc_newsletter_add_constraint(p_table TEXT, p_name TEXT, p_definition TEXT)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = p_name AND conrelid = p_table::regclass
    ) THEN
        EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I %s NOT VALID', p_table, p_name, p_definition);
    END IF;
    BEGIN
        EXECUTE format('ALTER TABLE %s VALIDATE CONSTRAINT %I', p_table, p_name);
    EXCEPTION WHEN foreign_key_violation OR check_violation THEN
        RAISE NOTICE 'OC_NEWSLETTER_CONSTRAINT_LEFT_NOT_VALID: %.% (legacy rows require reconciliation)', p_table, p_name;
    END;
END;
$$;

-- ---------------------------------------------------------------------------
-- Newsletter subscription settings (one row per subscriber constituent).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oc_communications.newsletter_subscription_settings (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    constituent_id BIGINT NOT NULL,
    public_constituent_id UUID NOT NULL,
    display_name TEXT,
    topics TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    frequency TEXT NOT NULL DEFAULT 'weekly'
        CHECK (frequency IN ('immediate', 'daily', 'weekly', 'monthly', 'quarterly')),
    format TEXT NOT NULL DEFAULT 'html' CHECK (format IN ('html', 'plain')),
    subscribed_at TIMESTAMPTZ,
    unsubscribed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, constituent_id),
    UNIQUE (organization_id, public_constituent_id),
    CONSTRAINT fk_newsletter_settings_tenant_constituent
        FOREIGN KEY (organization_id, constituent_id)
        REFERENCES oc_constituent.constituents (owner_organization_id, id) ON DELETE RESTRICT
);

COMMENT ON TABLE oc_communications.newsletter_subscription_settings IS
    'Newsletter topics, cadence and format per tenant-owned constituent. Subscription STATE is not stored here: it is the latest oc_constituent.communication_preferences row (email/community/*) plus active suppressions.';
COMMENT ON COLUMN oc_communications.newsletter_subscription_settings.public_constituent_id IS
    'Stable public id returned by the API: uuid5 of the normalized email (app.constituent_platform.service.constituent_id_for), unchanged from the Research Station era so existing clients and manage links keep working.';

-- ---------------------------------------------------------------------------
-- Newsletter archive (published issues; publishing here sends nothing).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oc_communications.newsletter_issues (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    newsletter_id UUID NOT NULL,
    title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 300),
    published_at TIMESTAMPTZ NOT NULL,
    topic_slugs TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    html_body TEXT NOT NULL,
    plain_text_body TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT 'community' CHECK (purpose IN (
        'transactional', 'membership_relationship', 'research_delivery', 'community',
        'fundraising', 'marketing', 'support', 'administrative'
    )),
    state TEXT NOT NULL DEFAULT 'completed'
        CHECK (state IN (
            'draft', 'awaiting_approval', 'approved', 'sending', 'completed',
            'partially_failed', 'cancelled'
        )),
    content_sha256 CHAR(64) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, newsletter_id)
);

CREATE INDEX IF NOT EXISTS ix_oc_newsletter_issues_org_published
    ON oc_communications.newsletter_issues (organization_id, state, published_at DESC);

COMMENT ON TABLE oc_communications.newsletter_issues IS
    'Web archive of published newsletter issues. Recording an issue here is not a send.';

-- ---------------------------------------------------------------------------
-- Contact inbox (public contact form).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oc_communications.inbound_contact_messages (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    reference_id TEXT NOT NULL CHECK (length(reference_id) BETWEEN 1 AND 80),
    category TEXT NOT NULL,
    name TEXT,
    normalized_email TEXT NOT NULL CHECK (normalized_email = LOWER(normalized_email)),
    subject TEXT,
    body TEXT NOT NULL,
    source TEXT,
    state TEXT NOT NULL DEFAULT 'received',
    review TEXT NOT NULL DEFAULT 'human_review_required'
        CHECK (review = 'human_review_required'),
    agent_exposure TEXT NOT NULL DEFAULT 'never_forwarded_to_agents'
        CHECK (agent_exposure = 'never_forwarded_to_agents'),
    content_trust TEXT NOT NULL DEFAULT 'untrusted_plain_text'
        CHECK (content_trust = 'untrusted_plain_text'),
    content_sha256 CHAR(64) NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, reference_id)
);

CREATE INDEX IF NOT EXISTS ix_oc_inbound_contact_org_received
    ON oc_communications.inbound_contact_messages (organization_id, received_at DESC);

COMMENT ON TABLE oc_communications.inbound_contact_messages IS
    'Public contact-form intake. Untrusted plain text for human review only: never forwarded to automated agents and never an authorization source for outbound contact.';

-- ---------------------------------------------------------------------------
-- Welcome intents: one per subscriber constituent, tenant-scoped audiences.
-- ---------------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS uq_oc_communications_intents_org_id
    ON oc_communications.intents (organization_id, id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_oc_communications_welcome_intent_per_constituent
    ON oc_communications.intents (organization_id, (audience_definition ->> 'constituent_id'))
    WHERE initiating_module = 'constituent_platform.welcome';

ALTER TABLE oc_communications.audience_snapshots
    ADD COLUMN IF NOT EXISTS organization_id BIGINT
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT;
ALTER TABLE oc_communications.audience_members
    ADD COLUMN IF NOT EXISTS organization_id BIGINT
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_oc_communications_snapshots_org_id
    ON oc_communications.audience_snapshots (organization_id, id);

SELECT pg_temp.oc_newsletter_add_constraint(
    'oc_communications.audience_snapshots', 'fk_audience_snapshots_tenant_intent',
    'FOREIGN KEY (organization_id, intent_id) REFERENCES oc_communications.intents (organization_id, id) ON DELETE RESTRICT');
SELECT pg_temp.oc_newsletter_add_constraint(
    'oc_communications.audience_members', 'fk_audience_members_tenant_snapshot',
    'FOREIGN KEY (organization_id, snapshot_id) REFERENCES oc_communications.audience_snapshots (organization_id, id) ON DELETE RESTRICT');
SELECT pg_temp.oc_newsletter_add_constraint(
    'oc_communications.audience_members', 'fk_audience_members_tenant_constituent',
    'FOREIGN KEY (organization_id, constituent_id) REFERENCES oc_constituent.constituents (owner_organization_id, id) ON DELETE RESTRICT');

COMMENT ON COLUMN oc_communications.audience_snapshots.organization_id IS
    'Tenant of the snapshot (matches its intent). Legacy NULL rows are invisible to oc_crm_runtime.';

-- ---------------------------------------------------------------------------
-- Row-level security for the runtime role.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    item TEXT;
BEGIN
    FOREACH item IN ARRAY ARRAY[
        'oc_communications.newsletter_subscription_settings',
        'oc_communications.newsletter_issues',
        'oc_communications.inbound_contact_messages',
        'oc_communications.audience_snapshots',
        'oc_communications.audience_members'
    ]
    LOOP
        EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', item);
        EXECUTE format('DROP POLICY IF EXISTS oc_crm_tenant_isolation ON %s', item);
        EXECUTE format(
            'CREATE POLICY oc_crm_tenant_isolation ON %s TO oc_crm_runtime '
            'USING (organization_id = oc_constituent.current_tenant_id()) '
            'WITH CHECK (organization_id = oc_constituent.current_tenant_id())',
            item
        );
    END LOOP;
END
$$;

-- Least privilege: no DELETE; archive and inbox are append-only to the runtime role;
-- frozen audience members are immutable (trigger) and only ever inserted.
GRANT SELECT, INSERT, UPDATE ON
    oc_communications.newsletter_subscription_settings,
    oc_communications.audience_snapshots
TO oc_crm_runtime;
GRANT SELECT, INSERT ON
    oc_communications.newsletter_issues,
    oc_communications.inbound_contact_messages,
    oc_communications.audience_members
TO oc_crm_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA oc_communications TO oc_crm_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA oc_constituent TO oc_crm_runtime;

COMMIT;
