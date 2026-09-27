-- Society CRM: member portal invites and operational job runs.
--
-- Idempotent. Apply after 20260927_society_crm_p1_tenant_isolation.sql.
--
-- * member_portal_invites: an administrator issues a single-use code for one
--   membership; the member redeems it while signed in, which creates an
--   organization identity binding (verification_method 'member_invite'). Only the
--   sha256 of the code is stored.
-- * crm_job_runs: platform-level record of background jobs (e.g. the membership
--   lifecycle job) so diagnostics can tell an administrator when a job last ran and
--   whether it failed. Written by the trusted backend/cron identity, not by the RLS
--   runtime role.

BEGIN;

ALTER TABLE oc_constituent.organization_identity_bindings
    DROP CONSTRAINT IF EXISTS organization_identity_bindings_verification_method_check;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_identity_bindings_verification_method'
          AND conrelid = 'oc_constituent.organization_identity_bindings'::regclass
    ) THEN
        ALTER TABLE oc_constituent.organization_identity_bindings
            ADD CONSTRAINT ck_identity_bindings_verification_method CHECK (verification_method IN (
                'platform_operator', 'admin_attested', 'verified_email_match', 'member_invite'
            ));
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS oc_constituent.member_portal_invites (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    constituent_id BIGINT NOT NULL,
    code_sha256 CHAR(64) NOT NULL UNIQUE,
    created_by_subject TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    redeemed_at TIMESTAMPTZ,
    redeemed_by_subject TEXT,
    revoked_at TIMESTAMPTZ,
    CHECK ((redeemed_at IS NULL) = (redeemed_by_subject IS NULL)),
    CONSTRAINT fk_portal_invites_tenant_constituent
        FOREIGN KEY (organization_id, constituent_id)
        REFERENCES oc_constituent.constituents (owner_organization_id, id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_oc_portal_invites_open
    ON oc_constituent.member_portal_invites (organization_id, constituent_id)
    WHERE redeemed_at IS NULL AND revoked_at IS NULL;

ALTER TABLE oc_constituent.member_portal_invites ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS oc_crm_tenant_isolation ON oc_constituent.member_portal_invites;
CREATE POLICY oc_crm_tenant_isolation ON oc_constituent.member_portal_invites TO oc_crm_runtime
    USING (organization_id = oc_constituent.current_tenant_id())
    WITH CHECK (organization_id = oc_constituent.current_tenant_id());
GRANT SELECT, INSERT, UPDATE ON oc_constituent.member_portal_invites TO oc_crm_runtime;
GRANT USAGE, SELECT ON SEQUENCE oc_constituent.member_portal_invites_id_seq TO oc_crm_runtime;

CREATE TABLE IF NOT EXISTS oc_constituent.crm_job_runs (
    id BIGSERIAL PRIMARY KEY,
    job_name TEXT NOT NULL CHECK (job_name ~ '^[a-z0-9_.-]{1,80}$'),
    organization_id BIGINT REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_code TEXT,
    CHECK ((status = 'running') = (finished_at IS NULL))
);

CREATE INDEX IF NOT EXISTS ix_oc_crm_job_runs_recent
    ON oc_constituent.crm_job_runs (job_name, started_at DESC);

-- Platform-level: no runtime-role grants and no runtime policy, so the RLS runtime
-- role can never read or write job history; owners are unaffected.
ALTER TABLE oc_constituent.crm_job_runs ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE oc_constituent.member_portal_invites IS
    'Single-use member portal link codes. Only the sha256 is stored; redemption creates a member_invite identity binding.';
COMMENT ON TABLE oc_constituent.crm_job_runs IS
    'Background job history for administrator diagnostics. Summaries carry counts, never member PII.';

COMMIT;
