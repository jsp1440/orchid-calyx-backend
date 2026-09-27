-- Society CRM P1: structural tenant isolation, membership lifecycle, identity binding.
--
-- Idempotent. Apply after:
--   migrations/20260823_oc_constituent_communications_foundation.sql
--   migrations/20260926_society_crm_p0_core.sql
--
-- What this adds:
--   * tenant-owned constituents (constituents.owner_organization_id) and composite
--     (organization_id, constituent_id) foreign keys so a Society A row can never
--     reference a Society B person, level, or membership -- enforced by PostgreSQL,
--     not by application WHERE clauses alone;
--   * organization_identity_bindings: an explicit, audited, per-organization binding
--     of a verified auth subject to a constituent. A subject is never silently
--     re-pointed at another person; rebinding requires an explicit revoke;
--   * membership lifecycle columns, renewal ledger (idempotent per renewal_key), and
--     household/family membership members;
--   * row-level security for the CRM tables, applied to the NOLOGIN role
--     oc_crm_runtime. The application enters that role with SET LOCAL ROLE and sets
--     the tenant with set_config(..., is_local => true) inside each transaction, so
--     neither the role nor the tenant survives COMMIT/ROLLBACK on a pooled
--     connection. With no tenant set, every policy evaluates to "no rows".
--
-- Trust note (see docs/security/NEON_PARTNER_DATA_RLS_DEPLOYMENT_PLAN.md): the tenant
-- setting is request context chosen by the trusted backend after it has
-- authenticated and authorized the caller. It is defence in depth against a missing
-- application filter, not an authentication boundary against a role that can issue
-- arbitrary SQL.

BEGIN;

-- ---------------------------------------------------------------------------
-- Runtime role (NOLOGIN; entered with SET LOCAL ROLE by the backend).
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'oc_crm_runtime') THEN
        CREATE ROLE oc_crm_runtime NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
END
$$;

-- The migrating identity must be able to enter the runtime role. Deployed backends
-- connecting as a different login need: GRANT oc_crm_runtime TO <backend_login>;
DO $$
BEGIN
    IF NOT pg_has_role(current_user, 'oc_crm_runtime', 'MEMBER') THEN
        EXECUTE format('GRANT oc_crm_runtime TO %I', current_user);
    END IF;
END
$$;

CREATE OR REPLACE FUNCTION oc_constituent.current_tenant_id()
RETURNS BIGINT
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('oc.crm_organization_id', true), '')::BIGINT
$$;

COMMENT ON FUNCTION oc_constituent.current_tenant_id() IS
    'Transaction-local CRM tenant chosen by the trusted backend. NULL means no tenant: RLS policies then match no rows.';

-- ---------------------------------------------------------------------------
-- Idempotent constraint helper (session-temporary).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION pg_temp.oc_crm_add_constraint(p_table TEXT, p_name TEXT, p_definition TEXT)
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
    -- Validate when existing rows allow it; legacy rows that predate tenant ownership
    -- leave the constraint NOT VALID (still enforced for every new or updated row).
    BEGIN
        EXECUTE format('ALTER TABLE %s VALIDATE CONSTRAINT %I', p_table, p_name);
    EXCEPTION WHEN foreign_key_violation OR check_violation THEN
        RAISE NOTICE 'OC_CRM_CONSTRAINT_LEFT_NOT_VALID: %.% (legacy rows require reconciliation)', p_table, p_name;
    END;
END;
$$;

-- ---------------------------------------------------------------------------
-- Tenant-owned constituents.
-- ---------------------------------------------------------------------------
ALTER TABLE oc_constituent.constituents
    ADD COLUMN IF NOT EXISTS owner_organization_id BIGINT
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_oc_constituent_constituents_owner_id
    ON oc_constituent.constituents (owner_organization_id, id);

COMMENT ON COLUMN oc_constituent.constituents.owner_organization_id IS
    'Organization that owns this CRM person record. Society CRM records are never shared across tenants; the same human in two societies is two tenant-owned records.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_oc_constituent_memberships_org_id
    ON oc_constituent.memberships (organization_id, id);

-- ---------------------------------------------------------------------------
-- Membership level lifecycle settings.
-- ---------------------------------------------------------------------------
ALTER TABLE oc_constituent.membership_levels
    ADD COLUMN IF NOT EXISTS grace_days INTEGER NOT NULL DEFAULT 30;
ALTER TABLE oc_constituent.membership_levels
    ADD COLUMN IF NOT EXISTS household_max_members INTEGER NOT NULL DEFAULT 1;
SELECT pg_temp.oc_crm_add_constraint(
    'oc_constituent.membership_levels', 'ck_membership_levels_grace_days',
    'CHECK (grace_days >= 0 AND grace_days <= 366)');
SELECT pg_temp.oc_crm_add_constraint(
    'oc_constituent.membership_levels', 'ck_membership_levels_household_max',
    'CHECK (household_max_members >= 1 AND household_max_members <= 20)');

-- ---------------------------------------------------------------------------
-- Membership lifecycle columns.
-- ---------------------------------------------------------------------------
ALTER TABLE oc_constituent.memberships ADD COLUMN IF NOT EXISTS last_renewed_at TIMESTAMPTZ;
ALTER TABLE oc_constituent.memberships ADD COLUMN IF NOT EXISTS status_changed_at TIMESTAMPTZ;
ALTER TABLE oc_constituent.memberships ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ;
ALTER TABLE oc_constituent.memberships ADD COLUMN IF NOT EXISTS cancellation_reason TEXT;
SELECT pg_temp.oc_crm_add_constraint(
    'oc_constituent.memberships', 'ck_memberships_cancelled_at',
    'CHECK ((status = ''cancelled'') = (cancelled_at IS NOT NULL))');

-- ---------------------------------------------------------------------------
-- Composite tenant foreign keys.
-- ---------------------------------------------------------------------------
SELECT pg_temp.oc_crm_add_constraint(
    'oc_constituent.memberships', 'fk_memberships_tenant_constituent',
    'FOREIGN KEY (organization_id, constituent_id) REFERENCES oc_constituent.constituents (owner_organization_id, id) ON DELETE RESTRICT');
SELECT pg_temp.oc_crm_add_constraint(
    'oc_constituent.memberships', 'fk_memberships_tenant_level',
    'FOREIGN KEY (organization_id, level_code) REFERENCES oc_constituent.membership_levels (organization_id, code) ON DELETE RESTRICT ON UPDATE RESTRICT');
SELECT pg_temp.oc_crm_add_constraint(
    'oc_constituent.organization_staff_roles', 'fk_staff_roles_tenant_constituent',
    'FOREIGN KEY (organization_id, constituent_id) REFERENCES oc_constituent.constituents (owner_organization_id, id) ON DELETE RESTRICT');
SELECT pg_temp.oc_crm_add_constraint(
    'oc_constituent.external_record_links', 'fk_external_links_tenant_constituent',
    'FOREIGN KEY (organization_id, constituent_id) REFERENCES oc_constituent.constituents (owner_organization_id, id) ON DELETE RESTRICT');
SELECT pg_temp.oc_crm_add_constraint(
    'oc_constituent.external_record_links', 'fk_external_links_tenant_membership',
    'FOREIGN KEY (organization_id, membership_id) REFERENCES oc_constituent.memberships (organization_id, id) ON DELETE RESTRICT');
SELECT pg_temp.oc_crm_add_constraint(
    'oc_constituent.email_addresses', 'fk_email_addresses_tenant_constituent',
    'FOREIGN KEY (organization_id, constituent_id) REFERENCES oc_constituent.constituents (owner_organization_id, id) ON DELETE RESTRICT');
SELECT pg_temp.oc_crm_add_constraint(
    'oc_constituent.phone_numbers', 'fk_phone_numbers_tenant_constituent',
    'FOREIGN KEY (organization_id, constituent_id) REFERENCES oc_constituent.constituents (owner_organization_id, id) ON DELETE RESTRICT');
SELECT pg_temp.oc_crm_add_constraint(
    'oc_constituent.postal_addresses', 'fk_postal_addresses_tenant_constituent',
    'FOREIGN KEY (organization_id, constituent_id) REFERENCES oc_constituent.constituents (owner_organization_id, id) ON DELETE RESTRICT');
SELECT pg_temp.oc_crm_add_constraint(
    'oc_constituent.entitlements', 'fk_entitlements_tenant_constituent',
    'FOREIGN KEY (organization_id, constituent_id) REFERENCES oc_constituent.constituents (owner_organization_id, id) ON DELETE RESTRICT');
SELECT pg_temp.oc_crm_add_constraint(
    'oc_constituent.communication_preferences', 'fk_preferences_tenant_constituent',
    'FOREIGN KEY (organization_id, constituent_id) REFERENCES oc_constituent.constituents (owner_organization_id, id) ON DELETE RESTRICT');
SELECT pg_temp.oc_crm_add_constraint(
    'oc_constituent.suppressions', 'fk_suppressions_tenant_constituent',
    'FOREIGN KEY (organization_id, constituent_id) REFERENCES oc_constituent.constituents (owner_organization_id, id) ON DELETE RESTRICT');

-- ---------------------------------------------------------------------------
-- Per-organization identity bindings (verified auth subject -> tenant person).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oc_constituent.organization_identity_bindings (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    constituent_id BIGINT NOT NULL,
    auth_subject TEXT NOT NULL,
    verification_method TEXT NOT NULL CHECK (verification_method IN (
        'platform_operator', 'admin_attested', 'verified_email_match'
    )),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    bound_by_subject TEXT NOT NULL,
    bound_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at TIMESTAMPTZ,
    revoked_by_subject TEXT,
    CHECK ((status = 'revoked') = (revoked_at IS NOT NULL)),
    CONSTRAINT fk_identity_bindings_tenant_constituent
        FOREIGN KEY (organization_id, constituent_id)
        REFERENCES oc_constituent.constituents (owner_organization_id, id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_oc_identity_bindings_active_subject
    ON oc_constituent.organization_identity_bindings (organization_id, auth_subject)
    WHERE status = 'active';
CREATE UNIQUE INDEX IF NOT EXISTS uq_oc_identity_bindings_active_constituent
    ON oc_constituent.organization_identity_bindings (organization_id, constituent_id)
    WHERE status = 'active';

-- auth_subject and constituent_id are immutable on a binding row: rebinding is a
-- revoke plus a new, separately audited binding.
CREATE OR REPLACE FUNCTION oc_constituent.reject_identity_binding_repoint()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.auth_subject IS DISTINCT FROM OLD.auth_subject
       OR NEW.constituent_id IS DISTINCT FROM OLD.constituent_id
       OR NEW.organization_id IS DISTINCT FROM OLD.organization_id THEN
        RAISE EXCEPTION 'IDENTITY_BINDING_IMMUTABLE';
    END IF;
    IF OLD.status = 'revoked' AND NEW.status <> 'revoked' THEN
        RAISE EXCEPTION 'IDENTITY_BINDING_REVOCATION_FINAL';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_reject_identity_binding_repoint
    ON oc_constituent.organization_identity_bindings;
CREATE TRIGGER trg_reject_identity_binding_repoint
BEFORE UPDATE ON oc_constituent.organization_identity_bindings
FOR EACH ROW EXECUTE FUNCTION oc_constituent.reject_identity_binding_repoint();

-- ---------------------------------------------------------------------------
-- Renewal ledger: one row per applied renewal; renewal_key makes retries safe.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oc_constituent.membership_renewals (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    membership_id BIGINT NOT NULL,
    renewal_key TEXT NOT NULL CHECK (length(renewal_key) BETWEEN 1 AND 200),
    level_code TEXT NOT NULL,
    term_months INTEGER NOT NULL CHECK (term_months > 0),
    previous_status TEXT NOT NULL,
    previous_expires_at TIMESTAMPTZ,
    new_starts_at TIMESTAMPTZ NOT NULL,
    new_expires_at TIMESTAMPTZ NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN (
        'admin', 'offline_payment', 'online_payment', 'import'
    )),
    source_ref TEXT,
    actor_subject TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, renewal_key),
    CHECK (new_expires_at > new_starts_at),
    CONSTRAINT fk_membership_renewals_tenant_membership
        FOREIGN KEY (organization_id, membership_id)
        REFERENCES oc_constituent.memberships (organization_id, id) ON DELETE RESTRICT
);

DROP TRIGGER IF EXISTS trg_reject_membership_renewal_mutation
    ON oc_constituent.membership_renewals;
CREATE TRIGGER trg_reject_membership_renewal_mutation
BEFORE UPDATE OR DELETE ON oc_constituent.membership_renewals
FOR EACH ROW EXECUTE FUNCTION oc_constituent.reject_crm_audit_mutation();

-- ---------------------------------------------------------------------------
-- Household / family membership: additional people covered by one membership.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oc_constituent.membership_household_members (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    membership_id BIGINT NOT NULL,
    constituent_id BIGINT NOT NULL,
    relationship TEXT NOT NULL DEFAULT 'household'
        CHECK (relationship IN ('household', 'partner', 'child', 'other')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'removed')),
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    removed_at TIMESTAMPTZ,
    CHECK ((status = 'removed') = (removed_at IS NOT NULL)),
    CONSTRAINT fk_household_tenant_membership
        FOREIGN KEY (organization_id, membership_id)
        REFERENCES oc_constituent.memberships (organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_household_tenant_constituent
        FOREIGN KEY (organization_id, constituent_id)
        REFERENCES oc_constituent.constituents (owner_organization_id, id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_oc_household_active_person
    ON oc_constituent.membership_household_members (organization_id, constituent_id)
    WHERE status = 'active';

-- ---------------------------------------------------------------------------
-- Row-level security for the runtime role.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    item RECORD;
BEGIN
    FOR item IN
        SELECT * FROM (VALUES
            ('oc_constituent.membership_levels', 'organization_id'),
            ('oc_constituent.organization_staff_roles', 'organization_id'),
            ('oc_constituent.external_record_links', 'organization_id'),
            ('oc_constituent.crm_audit_events', 'organization_id'),
            ('oc_constituent.memberships', 'organization_id'),
            ('oc_constituent.organization_identity_bindings', 'organization_id'),
            ('oc_constituent.membership_renewals', 'organization_id'),
            ('oc_constituent.membership_household_members', 'organization_id'),
            ('oc_constituent.email_addresses', 'organization_id'),
            ('oc_constituent.phone_numbers', 'organization_id'),
            ('oc_constituent.postal_addresses', 'organization_id'),
            ('oc_constituent.entitlements', 'organization_id'),
            ('oc_constituent.communication_preferences', 'organization_id'),
            ('oc_constituent.suppressions', 'organization_id'),
            ('oc_communications.intents', 'organization_id'),
            ('oc_constituent.constituents', 'owner_organization_id'),
            ('oc_constituent.organizations', 'id')
        ) AS t(table_name, tenant_column)
    LOOP
        EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', item.table_name);
        EXECUTE format('DROP POLICY IF EXISTS oc_crm_tenant_isolation ON %s', item.table_name);
        EXECUTE format(
            'CREATE POLICY oc_crm_tenant_isolation ON %s TO oc_crm_runtime '
            'USING (%I = oc_constituent.current_tenant_id()) '
            'WITH CHECK (%I = oc_constituent.current_tenant_id())',
            item.table_name, item.tenant_column, item.tenant_column
        );
    END LOOP;
END
$$;

-- Least privilege: no DELETE anywhere (removal is a status transition), audit and
-- ledger tables are append-only, organizations are read-only to the runtime role.
GRANT USAGE ON SCHEMA oc_constituent TO oc_crm_runtime;
GRANT USAGE ON SCHEMA oc_communications TO oc_crm_runtime;
GRANT EXECUTE ON FUNCTION oc_constituent.current_tenant_id() TO oc_crm_runtime;
GRANT SELECT ON oc_constituent.organizations TO oc_crm_runtime;
GRANT SELECT, INSERT, UPDATE ON
    oc_constituent.constituents,
    oc_constituent.membership_levels,
    oc_constituent.organization_staff_roles,
    oc_constituent.external_record_links,
    oc_constituent.memberships,
    oc_constituent.organization_identity_bindings,
    oc_constituent.membership_household_members,
    oc_constituent.email_addresses,
    oc_constituent.phone_numbers,
    oc_constituent.postal_addresses,
    oc_constituent.entitlements,
    oc_constituent.communication_preferences,
    oc_constituent.suppressions,
    oc_communications.intents
TO oc_crm_runtime;
GRANT SELECT, INSERT ON
    oc_constituent.crm_audit_events,
    oc_constituent.membership_renewals
TO oc_crm_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA oc_constituent TO oc_crm_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA oc_communications TO oc_crm_runtime;

COMMENT ON TABLE oc_constituent.organization_identity_bindings IS
    'Per-organization binding of a verified external auth subject to a tenant-owned constituent. Staff authority resolves only through an active binding in the same organization.';
COMMENT ON TABLE oc_constituent.membership_renewals IS
    'Append-only renewal ledger. UNIQUE (organization_id, renewal_key) makes payment-triggered renewals apply exactly once.';
COMMENT ON TABLE oc_constituent.membership_household_members IS
    'Additional people covered by a household/family membership. Dues and status live on the primary membership only.';

COMMIT;
