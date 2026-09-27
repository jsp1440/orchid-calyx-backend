-- Society CRM: per-organization settings and public profile.
--
-- Idempotent. Apply after 20260927_society_crm_p1_tenant_isolation.sql.
--
-- A society configures its own name, branding and public profile as data, so a
-- second society needs no code change. The runtime role may update only the
-- display name and settings of the organization it is bound to (RLS + column grant).

BEGIN;

ALTER TABLE oc_constituent.organizations
    ADD COLUMN IF NOT EXISTS settings JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_organizations_settings_object'
          AND conrelid = 'oc_constituent.organizations'::regclass
    ) THEN
        ALTER TABLE oc_constituent.organizations
            ADD CONSTRAINT ck_organizations_settings_object CHECK (jsonb_typeof(settings) = 'object');
    END IF;
END
$$;

GRANT UPDATE (display_name, settings, updated_at) ON oc_constituent.organizations TO oc_crm_runtime;

COMMENT ON COLUMN oc_constituent.organizations.settings IS
    'Society-managed configuration: branding, public profile, join page. Validated by the application; public fields are listed in society_profile.PUBLIC_SETTING_KEYS.';

COMMIT;
