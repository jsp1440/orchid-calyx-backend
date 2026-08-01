BEGIN;

CREATE TABLE IF NOT EXISTS calyx_journalism_evidence_packets (
    packet_id VARCHAR(36) PRIMARY KEY,
    owner_subject TEXT NOT NULL,
    actor_subject TEXT NOT NULL,
    generation_mode VARCHAR(32) NOT NULL,
    payload JSONB NOT NULL,
    request_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_calyx_journalism_packets_owner_created
    ON calyx_journalism_evidence_packets (owner_subject, created_at);

CREATE TABLE IF NOT EXISTS calyx_journalism_articles (
    article_id VARCHAR(36) PRIMARY KEY,
    owner_subject TEXT NOT NULL,
    actor_subject TEXT NOT NULL,
    generation_mode VARCHAR(32) NOT NULL,
    evidence_packet_id VARCHAR(36) NULL,
    payload JSONB NOT NULL,
    request_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_calyx_journalism_article_packet
        FOREIGN KEY (evidence_packet_id)
        REFERENCES calyx_journalism_evidence_packets(packet_id)
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_calyx_journalism_articles_owner_created
    ON calyx_journalism_articles (owner_subject, created_at);

COMMIT;

-- Downgrade, only after confirming no retained journalism artifacts are required:
-- DROP TABLE IF EXISTS calyx_journalism_articles;
-- DROP TABLE IF EXISTS calyx_journalism_evidence_packets;
