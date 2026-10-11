BEGIN;

CREATE SCHEMA IF NOT EXISTS oc_constituent;

CREATE TABLE IF NOT EXISTS oc_constituent.membership_levels (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    code TEXT NOT NULL CHECK (code = LOWER(code)),
    display_name TEXT NOT NULL,
    description TEXT,
    dues_amount_cents BIGINT NOT NULL DEFAULT 0 CHECK (dues_amount_cents >= 0),
    currency CHAR(3) NOT NULL DEFAULT 'USD' CHECK (currency = UPPER(currency)),
    term_months INTEGER NOT NULL DEFAULT 12 CHECK (term_months > 0),
    benefits JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, code)
);

CREATE TABLE IF NOT EXISTS oc_constituent.organization_staff_roles (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    constituent_id BIGINT NOT NULL
        REFERENCES oc_constituent.constituents(id) ON DELETE RESTRICT,
    role_code TEXT NOT NULL CHECK (role_code IN (
        'admin',
        'treasurer',
        'membership_editor',
        'communications_manager',
        'event_manager',
        'viewer'
    )),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'suspended', 'revoked')),
    granted_by_subject TEXT NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at TIMESTAMPTZ,
    UNIQUE (organization_id, constituent_id, role_code),
    CHECK ((status = 'revoked') = (revoked_at IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS ix_oc_constituent_staff_org_status
    ON oc_constituent.organization_staff_roles (organization_id, status, role_code);

CREATE TABLE IF NOT EXISTS oc_constituent.external_record_links (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    constituent_id BIGINT
        REFERENCES oc_constituent.constituents(id) ON DELETE RESTRICT,
    membership_id BIGINT
        REFERENCES oc_constituent.memberships(id) ON DELETE RESTRICT,
    source_system TEXT NOT NULL,
    source_record_type TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    source_payload_sha256 CHAR(64),
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, source_system, source_record_type, source_record_id),
    CHECK (constituent_id IS NOT NULL OR membership_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS oc_constituent.crm_audit_events (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    actor_subject TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    before_state JSONB,
    after_state JSONB,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_oc_constituent_crm_audit_org_created
    ON oc_constituent.crm_audit_events (organization_id, created_at DESC);

CREATE OR REPLACE FUNCTION oc_constituent.reject_crm_audit_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'CRM_AUDIT_IMMUTABLE';
END;
$$;

DROP TRIGGER IF EXISTS trg_reject_crm_audit_update
    ON oc_constituent.crm_audit_events;
CREATE TRIGGER trg_reject_crm_audit_update
BEFORE UPDATE OR DELETE ON oc_constituent.crm_audit_events
FOR EACH ROW EXECUTE FUNCTION oc_constituent.reject_crm_audit_mutation();

COMMENT ON TABLE oc_constituent.membership_levels IS
    'Organization-scoped membership level catalog. Configuration is shared by the one multi-tenant CRM; no per-society schema forks.';
COMMENT ON TABLE oc_constituent.organization_staff_roles IS
    'Society administrative roles. Ordinary membership alone never grants staff authority.';
COMMENT ON TABLE oc_constituent.external_record_links IS
    'Idempotent source keys for Neon/CSV/import reconciliation.';
COMMENT ON TABLE oc_constituent.crm_audit_events IS
    'Append-only CRM administrative audit trail. UPDATE and DELETE are rejected by trigger.';

COMMIT;
