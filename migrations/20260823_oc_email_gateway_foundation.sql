BEGIN;

CREATE SCHEMA IF NOT EXISTS oc_email;

CREATE TABLE IF NOT EXISTS oc_email.inbound_messages (
    id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    provider_message_id TEXT NOT NULL,
    internet_message_id TEXT,
    thread_id TEXT,
    sender TEXT NOT NULL,
    reply_to TEXT,
    recipients JSONB NOT NULL DEFAULT '[]'::jsonb,
    subject TEXT NOT NULL,
    body_text TEXT NOT NULL,
    received_at TIMESTAMPTZ,
    content_sha256 CHAR(64) NOT NULL,
    route TEXT NOT NULL CHECK (route IN ('research', 'support', 'bug', 'admin', 'review')),
    route_reason TEXT NOT NULL,
    trust_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    attachment_metadata JSONB NOT NULL DEFAULT '[]'::jsonb,
    intake_source_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (provider, provider_message_id)
);

CREATE INDEX IF NOT EXISTS ix_oc_email_inbound_internet_message_id
    ON oc_email.inbound_messages (internet_message_id)
    WHERE internet_message_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_oc_email_inbound_route_created
    ON oc_email.inbound_messages (route, created_at DESC);

CREATE TABLE IF NOT EXISTS oc_email.tickets (
    id BIGSERIAL PRIMARY KEY,
    inbound_message_id BIGINT NOT NULL UNIQUE
        REFERENCES oc_email.inbound_messages(id) ON DELETE RESTRICT,
    category TEXT NOT NULL CHECK (category IN ('support', 'bug', 'admin', 'review')),
    status TEXT NOT NULL DEFAULT 'new'
        CHECK (status IN ('new', 'triaged', 'in_progress', 'waiting_user', 'resolved', 'spam')),
    priority TEXT NOT NULL DEFAULT 'normal'
        CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    module_guess TEXT,
    assigned_to TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_oc_email_tickets_status_created
    ON oc_email.tickets (status, created_at DESC);

COMMENT ON SCHEMA oc_email IS
    'Untrusted inbound email transport ledger and operational ticket queue. Email content never grants runtime or scientific authority.';

COMMENT ON COLUMN oc_email.inbound_messages.intake_source_id IS
    'Optional reference to governed oc_intake source created for research/intelligence mail; presence does not imply canonical Knowledge Graph promotion.';

COMMIT;
