-- Society CRM money: payment ledger, offline payments, refunds, donations + receipts,
-- provider webhook idempotency.
--
-- Idempotent. Apply after:
--   migrations/20260823_oc_constituent_communications_foundation.sql
--   migrations/20260926_society_crm_p0_core.sql
--   migrations/20260927_society_crm_p1_tenant_isolation.sql
--
-- Design notes:
--   * Tables live in oc_constituent so the runtime role stays confined to the CRM
--     schemas (see test_runtime_role_is_least_privilege_and_confined_to_crm_schemas).
--   * No column may hold card numbers (PAN), CVV, bank account/routing numbers, or
--     provider secrets. Only the provider's opaque object id (e.g. pi_...) is kept.
--     A CHECK rejects 13+ digit runs (ignoring spaces/dashes) in free text, and
--     check_number is limited to 12 characters, so a PAN cannot be stored there.
--   * Raw webhook payloads are never stored: only their SHA-256 and minimal parsed
--     fields.
--   * Every table carries organization_id with composite tenant FKs, RLS policy
--     oc_crm_tenant_isolation for oc_crm_runtime, and no DELETE grant. Ledger tables
--     (payment_events, refunds, donations) are append-only (trigger + grants).

BEGIN;

-- True when text contains a run of 13 or more digits once spaces and dashes are
-- removed: the shape of a primary account number. Free text must never hold one.
CREATE OR REPLACE FUNCTION oc_constituent.crm_text_has_pan_like_digits(p_value TEXT)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT p_value IS NOT NULL AND regexp_replace(p_value, '[\s-]', '', 'g') ~ '[0-9]{13,}'
$$;

GRANT EXECUTE ON FUNCTION oc_constituent.crm_text_has_pan_like_digits(TEXT) TO oc_crm_runtime;

-- ---------------------------------------------------------------------------
-- Payments: one row per money movement into the organization.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oc_constituent.payments (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    constituent_id BIGINT NOT NULL,
    membership_id BIGINT,
    purpose TEXT NOT NULL CHECK (purpose IN ('membership_dues', 'donation', 'event', 'other')),
    amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
    currency CHAR(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    method TEXT NOT NULL CHECK (method IN (
        'check', 'cash', 'card_provider', 'bank_transfer_provider', 'other_offline'
    )),
    provider TEXT CHECK (provider IN ('stripe')),
    provider_payment_ref TEXT CHECK (provider_payment_ref ~ '^[A-Za-z0-9_]{1,255}$'),
    check_number TEXT CHECK (check_number ~ '^[A-Za-z0-9-]{1,12}$'),
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'succeeded', 'failed', 'refunded', 'partially_refunded', 'voided'
    )),
    refunded_amount_cents BIGINT NOT NULL DEFAULT 0,
    renewal_id BIGINT REFERENCES oc_constituent.membership_renewals(id) ON DELETE RESTRICT,
    membership_review_required BOOLEAN NOT NULL DEFAULT FALSE,
    received_at TIMESTAMPTZ NOT NULL,
    recorded_by_subject TEXT NOT NULL,
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 200),
    notes TEXT CHECK (length(notes) <= 500),
    voided_at TIMESTAMPTZ,
    void_reason TEXT CHECK (length(void_reason) <= 500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, idempotency_key),
    CONSTRAINT ck_payments_provider_pairing CHECK (
        (method IN ('card_provider', 'bank_transfer_provider')) = (provider IS NOT NULL)
        AND (provider IS NULL) = (provider_payment_ref IS NULL)
    ),
    CONSTRAINT ck_payments_check_number_only_for_checks CHECK (check_number IS NULL OR method = 'check'),
    CONSTRAINT ck_payments_refund_bounds CHECK (
        refunded_amount_cents >= 0 AND refunded_amount_cents <= amount_cents
        AND (status <> 'refunded' OR refunded_amount_cents = amount_cents)
        AND (status <> 'partially_refunded' OR (refunded_amount_cents > 0 AND refunded_amount_cents < amount_cents))
        AND (status IN ('refunded', 'partially_refunded') OR refunded_amount_cents = 0)
    ),
    CONSTRAINT ck_payments_void CHECK ((status = 'voided') = (voided_at IS NOT NULL)),
    CONSTRAINT ck_payments_no_pan_text CHECK (
        NOT oc_constituent.crm_text_has_pan_like_digits(notes)
        AND NOT oc_constituent.crm_text_has_pan_like_digits(void_reason)
    ),
    CONSTRAINT fk_payments_tenant_constituent
        FOREIGN KEY (organization_id, constituent_id)
        REFERENCES oc_constituent.constituents (owner_organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_payments_tenant_membership
        FOREIGN KEY (organization_id, membership_id)
        REFERENCES oc_constituent.memberships (organization_id, id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_oc_payments_org_id
    ON oc_constituent.payments (organization_id, id);
-- A provider object id is credited to exactly one ledger row, across all tenants.
CREATE UNIQUE INDEX IF NOT EXISTS uq_oc_payments_provider_ref
    ON oc_constituent.payments (provider, provider_payment_ref)
    WHERE provider IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_oc_payments_org_received
    ON oc_constituent.payments (organization_id, received_at DESC);
CREATE INDEX IF NOT EXISTS ix_oc_payments_org_membership
    ON oc_constituent.payments (organization_id, membership_id);

-- ---------------------------------------------------------------------------
-- Payment status history (append-only).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oc_constituent.payment_events (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    payment_id BIGINT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (length(reason) BETWEEN 1 AND 500),
    amount_cents BIGINT,
    actor_subject TEXT NOT NULL,
    provider_event_id TEXT CHECK (provider_event_id ~ '^[A-Za-z0-9_]{1,255}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_payment_events_no_pan_text CHECK (NOT oc_constituent.crm_text_has_pan_like_digits(reason)),
    CONSTRAINT fk_payment_events_tenant_payment
        FOREIGN KEY (organization_id, payment_id)
        REFERENCES oc_constituent.payments (organization_id, id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_oc_payment_events_payment
    ON oc_constituent.payment_events (organization_id, payment_id, id);

DROP TRIGGER IF EXISTS trg_reject_payment_event_mutation ON oc_constituent.payment_events;
CREATE TRIGGER trg_reject_payment_event_mutation
BEFORE UPDATE OR DELETE ON oc_constituent.payment_events
FOR EACH ROW EXECUTE FUNCTION oc_constituent.reject_crm_audit_mutation();

-- ---------------------------------------------------------------------------
-- Refunds (append-only; payments.refunded_amount_cents carries the running total).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oc_constituent.refunds (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    payment_id BIGINT NOT NULL,
    amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
    reason TEXT NOT NULL CHECK (length(reason) BETWEEN 1 AND 500),
    provider_refund_ref TEXT CHECK (provider_refund_ref ~ '^[A-Za-z0-9_]{1,255}$'),
    status TEXT NOT NULL DEFAULT 'succeeded' CHECK (status IN ('pending', 'succeeded', 'failed')),
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 200),
    recorded_by_subject TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, idempotency_key),
    CONSTRAINT ck_refunds_no_pan_text CHECK (NOT oc_constituent.crm_text_has_pan_like_digits(reason)),
    CONSTRAINT fk_refunds_tenant_payment
        FOREIGN KEY (organization_id, payment_id)
        REFERENCES oc_constituent.payments (organization_id, id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_oc_refunds_provider_ref
    ON oc_constituent.refunds (provider_refund_ref)
    WHERE provider_refund_ref IS NOT NULL;

DROP TRIGGER IF EXISTS trg_reject_refund_mutation ON oc_constituent.refunds;
CREATE TRIGGER trg_reject_refund_mutation
BEFORE UPDATE OR DELETE ON oc_constituent.refunds
FOR EACH ROW EXECUTE FUNCTION oc_constituent.reject_crm_audit_mutation();

-- ---------------------------------------------------------------------------
-- Donations and receipts.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oc_constituent.donation_receipt_counters (
    organization_id BIGINT PRIMARY KEY
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    last_receipt_number BIGINT NOT NULL CHECK (last_receipt_number >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_constituent.donations (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    constituent_id BIGINT NOT NULL,
    payment_id BIGINT NOT NULL,
    amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
    currency CHAR(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    designation TEXT NOT NULL CHECK (designation ~ '^[a-z0-9][a-z0-9_-]{0,39}$'),
    is_anonymous_to_public BOOLEAN NOT NULL DEFAULT FALSE,
    tax_deductible_cents BIGINT NOT NULL,
    receipt_number BIGINT NOT NULL CHECK (receipt_number > 0),
    receipt_issued_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, receipt_number),
    UNIQUE (organization_id, payment_id),
    CHECK (tax_deductible_cents >= 0 AND tax_deductible_cents <= amount_cents),
    CONSTRAINT fk_donations_tenant_constituent
        FOREIGN KEY (organization_id, constituent_id)
        REFERENCES oc_constituent.constituents (owner_organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_donations_tenant_payment
        FOREIGN KEY (organization_id, payment_id)
        REFERENCES oc_constituent.payments (organization_id, id) ON DELETE RESTRICT
);

DROP TRIGGER IF EXISTS trg_reject_donation_mutation ON oc_constituent.donations;
CREATE TRIGGER trg_reject_donation_mutation
BEFORE UPDATE OR DELETE ON oc_constituent.donations
FOR EACH ROW EXECUTE FUNCTION oc_constituent.reject_crm_audit_mutation();

-- ---------------------------------------------------------------------------
-- Provider webhook deliveries (idempotency + diagnostics). No raw payload.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oc_constituent.provider_webhook_events (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL
        REFERENCES oc_constituent.organizations(id) ON DELETE RESTRICT,
    provider TEXT NOT NULL CHECK (provider IN ('stripe')),
    provider_event_id TEXT NOT NULL CHECK (provider_event_id ~ '^[A-Za-z0-9_]{1,255}$'),
    event_type TEXT NOT NULL CHECK (length(event_type) BETWEEN 1 AND 100),
    payload_sha256 CHAR(64) NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    signature_verified BOOLEAN NOT NULL CHECK (signature_verified),
    provider_payment_ref TEXT CHECK (provider_payment_ref ~ '^[A-Za-z0-9_]{1,255}$'),
    amount_cents BIGINT,
    currency CHAR(3),
    payment_id BIGINT,
    processing_status TEXT NOT NULL DEFAULT 'received'
        CHECK (processing_status IN ('received', 'processed', 'ignored', 'failed')),
    error_code TEXT CHECK (length(error_code) <= 100),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_attempt_at TIMESTAMPTZ,
    processed_at TIMESTAMPTZ,
    UNIQUE (provider, provider_event_id),
    CHECK ((processing_status = 'failed') = (error_code IS NOT NULL)),
    CONSTRAINT fk_webhook_events_tenant_payment
        FOREIGN KEY (organization_id, payment_id)
        REFERENCES oc_constituent.payments (organization_id, id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_oc_webhook_events_org_status
    ON oc_constituent.provider_webhook_events (organization_id, processing_status, received_at DESC);

-- ---------------------------------------------------------------------------
-- Row-level security for the runtime role.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    item TEXT;
BEGIN
    FOREACH item IN ARRAY ARRAY[
        'oc_constituent.payments',
        'oc_constituent.payment_events',
        'oc_constituent.refunds',
        'oc_constituent.donation_receipt_counters',
        'oc_constituent.donations',
        'oc_constituent.provider_webhook_events'
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

-- Least privilege: UPDATE only where a state transition needs it; no DELETE anywhere.
GRANT SELECT, INSERT, UPDATE ON
    oc_constituent.payments,
    oc_constituent.donation_receipt_counters,
    oc_constituent.provider_webhook_events
TO oc_crm_runtime;
GRANT SELECT, INSERT ON
    oc_constituent.payment_events,
    oc_constituent.refunds,
    oc_constituent.donations
TO oc_crm_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA oc_constituent TO oc_crm_runtime;

COMMENT ON TABLE oc_constituent.payments IS
    'Tenant payment ledger. Holds only provider opaque ids (e.g. pi_...), never card numbers, CVV, bank credentials or provider secrets.';
COMMENT ON COLUMN oc_constituent.payments.check_number IS
    'Paper check serial number (<= 12 chars). Never a bank account or routing number.';
COMMENT ON COLUMN oc_constituent.payments.membership_review_required IS
    'Set when a dues payment that renewed a membership is refunded: an administrator decides whether the membership term changes.';
COMMENT ON TABLE oc_constituent.payment_events IS
    'Append-only payment status history. UPDATE and DELETE are rejected by trigger.';
COMMENT ON TABLE oc_constituent.refunds IS
    'Append-only refund ledger. payments.refunded_amount_cents is bounded by amount_cents.';
COMMENT ON TABLE oc_constituent.donations IS
    'Append-only donation records with per-organization sequential receipt numbers.';
COMMENT ON TABLE oc_constituent.donation_receipt_counters IS
    'Per-organization receipt number allocator; the row is locked by the allocating transaction.';
COMMENT ON TABLE oc_constituent.provider_webhook_events IS
    'Verified provider webhook deliveries: idempotency and diagnostics. Stores the payload SHA-256 and minimal parsed fields, never the raw payload.';

COMMIT;
