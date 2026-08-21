-- Partner-data security foundation: persistent governance registry.
-- Additive only. Does not ingest partner data and does not weaken existing access.
--
-- This migration deliberately creates policy/authorization metadata separately
-- from scientific domain tables. Future protected datasets must bind records to
-- one or more policies and enforce those policies at every delivery surface.

CREATE SCHEMA IF NOT EXISTS oc_security;
REVOKE ALL ON SCHEMA oc_security FROM PUBLIC;

CREATE TABLE IF NOT EXISTS oc_security.partner_organizations (
    partner_id text PRIMARY KEY,
    display_name text NOT NULL,
    authority_name text NOT NULL,
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'inactive', 'suspended')),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS oc_security.partner_agreements (
    agreement_id text PRIMARY KEY,
    partner_id text NOT NULL
        REFERENCES oc_security.partner_organizations(partner_id) ON DELETE RESTRICT,
    agreement_reference text NOT NULL,
    title text NOT NULL,
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'expired', 'revoked')),
    effective_at timestamptz,
    expires_at timestamptz,
    terms_hash_sha256 text
        CHECK (terms_hash_sha256 IS NULL OR terms_hash_sha256 ~ '^[0-9a-f]{64}$'),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (expires_at IS NULL OR effective_at IS NULL OR expires_at > effective_at),
    UNIQUE (partner_id, agreement_reference)
);

CREATE TABLE IF NOT EXISTS oc_security.dataset_policies (
    policy_id text PRIMARY KEY,
    partner_id text NOT NULL
        REFERENCES oc_security.partner_organizations(partner_id) ON DELETE RESTRICT,
    agreement_id text
        REFERENCES oc_security.partner_agreements(agreement_id) ON DELETE RESTRICT,
    dataset_key text NOT NULL,
    policy_version integer NOT NULL DEFAULT 1 CHECK (policy_version > 0),
    sensitivity text NOT NULL
        CHECK (sensitivity IN (
            'PUBLIC',
            'ATTRIBUTED',
            'RESEARCH_RESTRICTED',
            'SENSITIVE_CONSERVATION',
            'SEALED_PARTNER'
        )),
    required_capabilities text[] NOT NULL DEFAULT ARRAY[]::text[],
    allowed_purposes text[] NOT NULL DEFAULT ARRAY[]::text[],
    attribution_required boolean NOT NULL DEFAULT true,
    allow_export boolean NOT NULL DEFAULT false,
    allow_model_processing boolean NOT NULL DEFAULT false,
    approved_model_providers text[] NOT NULL DEFAULT ARRAY[]::text[],
    default_disclosure text NOT NULL DEFAULT 'DENY'
        CHECK (default_disclosure IN (
            'FULL', 'GENERALIZED', 'AGGREGATE_ONLY', 'EXISTENCE_ONLY', 'DENY'
        )),
    location_disclosure text NOT NULL DEFAULT 'DENY'
        CHECK (location_disclosure IN (
            'FULL', 'GENERALIZED', 'AGGREGATE_ONLY', 'EXISTENCE_ONLY', 'DENY'
        )),
    image_disclosure text NOT NULL DEFAULT 'DENY'
        CHECK (image_disclosure IN (
            'FULL', 'GENERALIZED', 'AGGREGATE_ONLY', 'EXISTENCE_ONLY', 'DENY'
        )),
    embargo_until timestamptz,
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'superseded', 'revoked')),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (partner_id, dataset_key, policy_version)
);

CREATE INDEX IF NOT EXISTS idx_oc_security_dataset_policies_lookup
    ON oc_security.dataset_policies (partner_id, dataset_key, status);

CREATE TABLE IF NOT EXISTS oc_security.research_projects (
    project_id text PRIMARY KEY,
    project_name text NOT NULL,
    purpose text NOT NULL,
    status text NOT NULL DEFAULT 'proposed'
        CHECK (status IN ('proposed', 'approved', 'suspended', 'closed')),
    approved_at timestamptz,
    expires_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS oc_security.project_memberships (
    project_id text NOT NULL
        REFERENCES oc_security.research_projects(project_id) ON DELETE CASCADE,
    principal_id text NOT NULL,
    project_role text NOT NULL DEFAULT 'researcher',
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'suspended', 'revoked', 'expired')),
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_until timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, principal_id),
    CHECK (valid_until IS NULL OR valid_until > valid_from)
);

CREATE TABLE IF NOT EXISTS oc_security.principal_entitlements (
    entitlement_id text PRIMARY KEY,
    principal_id text NOT NULL,
    project_id text
        REFERENCES oc_security.research_projects(project_id) ON DELETE CASCADE,
    partner_id text
        REFERENCES oc_security.partner_organizations(partner_id) ON DELETE RESTRICT,
    dataset_key text,
    capability text NOT NULL,
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'suspended', 'revoked', 'expired')),
    granted_by text NOT NULL,
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_until timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (valid_until IS NULL OR valid_until > valid_from)
);

CREATE INDEX IF NOT EXISTS idx_oc_security_entitlements_principal
    ON oc_security.principal_entitlements (principal_id, status, capability);
CREATE INDEX IF NOT EXISTS idx_oc_security_entitlements_dataset
    ON oc_security.principal_entitlements (partner_id, dataset_key, status);

-- A record may be governed by more than one policy. Consumers must evaluate ALL
-- active bindings and apply the most restrictive combined result. A permissive
-- policy must never widen a more restrictive policy attached to the same record.
CREATE TABLE IF NOT EXISTS oc_security.record_policy_bindings (
    binding_id text PRIMARY KEY,
    record_domain text NOT NULL,
    record_type text NOT NULL,
    record_id text NOT NULL,
    policy_id text NOT NULL
        REFERENCES oc_security.dataset_policies(policy_id) ON DELETE RESTRICT,
    source_record_id text,
    source_org text,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (record_domain, record_type, record_id, policy_id)
);

CREATE INDEX IF NOT EXISTS idx_oc_security_record_policy_record
    ON oc_security.record_policy_bindings (
        record_domain, record_type, record_id, active
    );
CREATE INDEX IF NOT EXISTS idx_oc_security_record_policy_policy
    ON oc_security.record_policy_bindings (policy_id, active);

-- Append-oriented audit ledger for policy decisions and protected-data actions.
-- Application code should record ALLOW and DENY decisions. No DELETE/UPDATE
-- capability should be granted to ordinary application roles.
CREATE TABLE IF NOT EXISTS oc_security.access_audit_events (
    event_id text PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    principal_id text,
    auth_type text,
    project_id text,
    purpose text,
    action text NOT NULL,
    record_domain text,
    record_type text,
    record_id text,
    policy_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
    allowed boolean NOT NULL,
    reason_codes text[] NOT NULL DEFAULT ARRAY[]::text[],
    disclosure text,
    location_disclosure text,
    image_disclosure text,
    model_provider text,
    export_requested boolean NOT NULL DEFAULT false,
    model_processing_requested boolean NOT NULL DEFAULT false,
    request_id text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_oc_security_audit_principal_time
    ON oc_security.access_audit_events (principal_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_oc_security_audit_record_time
    ON oc_security.access_audit_events (
        record_domain, record_type, record_id, occurred_at DESC
    );
CREATE INDEX IF NOT EXISTS idx_oc_security_audit_policy_time
    ON oc_security.access_audit_events USING gin (policy_ids);

-- Policy changes need their own immutable evidence trail so a later reviewer can
-- determine which restrictions applied at the time of a scientific action.
CREATE TABLE IF NOT EXISTS oc_security.policy_change_events (
    change_id text PRIMARY KEY,
    policy_id text NOT NULL
        REFERENCES oc_security.dataset_policies(policy_id) ON DELETE RESTRICT,
    changed_at timestamptz NOT NULL DEFAULT now(),
    changed_by text NOT NULL,
    change_type text NOT NULL,
    previous_policy jsonb,
    new_policy jsonb NOT NULL,
    reason text NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_oc_security_policy_change_time
    ON oc_security.policy_change_events (policy_id, changed_at DESC);

-- Defense in depth: remove implicit PUBLIC privileges even if cluster defaults
-- are changed later. Explicit service/reviewer grants belong in a deployment
-- migration after the actual Neon runtime roles are identified and validated.
REVOKE ALL ON ALL TABLES IN SCHEMA oc_security FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA oc_security FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA oc_security FROM PUBLIC;

-- RLS is enabled and forced on the two surfaces that could expose record-level
-- governance links or access-history. No permissive policies are installed here,
-- so access is default-deny until a later deployment-specific migration binds
-- verified runtime roles and trusted policy context.
ALTER TABLE oc_security.record_policy_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE oc_security.record_policy_bindings FORCE ROW LEVEL SECURITY;
ALTER TABLE oc_security.access_audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE oc_security.access_audit_events FORCE ROW LEVEL SECURITY;

COMMENT ON SCHEMA oc_security IS
    'Partner-data governance registry; restricted scientific data remains source-authoritative and policy-bound.';
COMMENT ON TABLE oc_security.record_policy_bindings IS
    'Record-to-policy bindings. Multiple active policies compose restrictively; aggregation must not erase bindings.';
COMMENT ON TABLE oc_security.access_audit_events IS
    'Append-oriented audit evidence for protected-data access and policy decisions.';
