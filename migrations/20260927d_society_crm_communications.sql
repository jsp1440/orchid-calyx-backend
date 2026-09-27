-- Society CRM communications: tenant-scoped approvals, delivery attempts, delivery events.
--
-- Idempotent. Apply after 20260927b_constituent_newsletter_canonical.sql (which adds
-- organization_id to audience snapshots/members and uq_oc_communications_intents_org_id).
--
-- No outbound provider is configured here. Delivery attempts record what a
-- provider-neutral adapter did; bounce/complaint events become suppressions.

BEGIN;

CREATE OR REPLACE FUNCTION pg_temp.oc_crm_add_constraint(p_table TEXT, p_name TEXT, p_definition TEXT)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = p_name AND conrelid = p_table::regclass
    ) THEN
        EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I %s NOT VALID', p_table, p_name, p_definition);
    END IF;
    BEGIN
        EXECUTE format('ALTER TABLE %s VALIDATE CONSTRAINT %I', p_table, p_name);
    EXCEPTION WHEN foreign_key_violation OR check_violation THEN
        RAISE NOTICE 'OC_CRM_CONSTRAINT_LEFT_NOT_VALID: %.%', p_table, p_name;
    END;
END;
$$;

-- Approval events bound to the same tenant as their intent.
ALTER TABLE oc_communications.approval_events
    ADD COLUMN IF NOT EXISTS organization_id BIGINT
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT;
SELECT pg_temp.oc_crm_add_constraint(
    'oc_communications.approval_events', 'fk_approval_events_tenant_intent',
    'FOREIGN KEY (organization_id, intent_id) REFERENCES oc_communications.intents (organization_id, id) ON DELETE RESTRICT');

DROP TRIGGER IF EXISTS trg_reject_approval_event_mutation ON oc_communications.approval_events;
CREATE TRIGGER trg_reject_approval_event_mutation
BEFORE UPDATE OR DELETE ON oc_communications.approval_events
FOR EACH ROW EXECUTE FUNCTION oc_constituent.reject_crm_audit_mutation();

CREATE UNIQUE INDEX IF NOT EXISTS uq_oc_audience_members_org_id
    ON oc_communications.audience_members (organization_id, id);

CREATE TABLE IF NOT EXISTS oc_communications.delivery_attempts (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    intent_id BIGINT NOT NULL,
    audience_member_id BIGINT NOT NULL,
    normalized_email TEXT NOT NULL CHECK (normalized_email = LOWER(normalized_email)),
    provider TEXT NOT NULL CHECK (provider ~ '^[a-z0-9_-]{1,40}$'),
    provider_message_ref TEXT,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN (
        'queued', 'sent', 'delivered', 'deferred', 'bounced', 'complained', 'failed', 'suppressed'
    )),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error_code TEXT,
    next_attempt_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, intent_id, audience_member_id),
    CONSTRAINT fk_delivery_attempts_tenant_intent
        FOREIGN KEY (organization_id, intent_id)
        REFERENCES oc_communications.intents (organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_delivery_attempts_tenant_member
        FOREIGN KEY (organization_id, audience_member_id)
        REFERENCES oc_communications.audience_members (organization_id, id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_oc_delivery_attempts_status
    ON oc_communications.delivery_attempts (organization_id, status, next_attempt_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_oc_delivery_attempts_provider_ref
    ON oc_communications.delivery_attempts (provider, provider_message_ref)
    WHERE provider_message_ref IS NOT NULL;

CREATE TABLE IF NOT EXISTS oc_communications.delivery_events (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    provider TEXT NOT NULL,
    provider_event_id TEXT NOT NULL,
    delivery_attempt_id BIGINT,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'delivered', 'soft_bounce', 'hard_bounce', 'complaint', 'unsubscribe'
    )),
    normalized_email TEXT NOT NULL CHECK (normalized_email = LOWER(normalized_email)),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (provider, provider_event_id)
);

DROP TRIGGER IF EXISTS trg_reject_delivery_event_mutation ON oc_communications.delivery_events;
CREATE TRIGGER trg_reject_delivery_event_mutation
BEFORE UPDATE OR DELETE ON oc_communications.delivery_events
FOR EACH ROW EXECUTE FUNCTION oc_constituent.reject_crm_audit_mutation();

DO $$
DECLARE
    item TEXT;
BEGIN
    FOREACH item IN ARRAY ARRAY[
        'oc_communications.approval_events',
        'oc_communications.delivery_attempts',
        'oc_communications.delivery_events'
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

GRANT SELECT, INSERT ON oc_communications.approval_events TO oc_crm_runtime;
GRANT SELECT, INSERT, UPDATE ON oc_communications.delivery_attempts TO oc_crm_runtime;
GRANT SELECT, INSERT ON oc_communications.delivery_events TO oc_crm_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA oc_communications TO oc_crm_runtime;

COMMENT ON TABLE oc_communications.delivery_attempts IS
    'One row per allowed recipient of a dispatched intent. Suppressed recipients never get an attempt.';
COMMENT ON TABLE oc_communications.delivery_events IS
    'Append-only provider delivery feedback. Hard bounces and complaints create suppressions that override preferences.';

COMMIT;
