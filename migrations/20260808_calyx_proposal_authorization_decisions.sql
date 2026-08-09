CREATE TABLE IF NOT EXISTS calyx_proposal_authorization_decisions (
    record_id VARCHAR(36) PRIMARY KEY,
    manifest_digest VARCHAR(64) NOT NULL,
    review_class VARCHAR(40) NOT NULL,
    authorization_digest VARCHAR(64) NOT NULL UNIQUE,
    payload_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_calyx_proposal_authorization_manifest_class
        UNIQUE (manifest_digest, review_class),
    CONSTRAINT ck_calyx_proposal_authorization_review_class
        CHECK (review_class IN ('operational', 'security'))
);

CREATE INDEX IF NOT EXISTS ix_calyx_proposal_authorization_manifest
    ON calyx_proposal_authorization_decisions(manifest_digest);
CREATE INDEX IF NOT EXISTS ix_calyx_proposal_authorization_review_class
    ON calyx_proposal_authorization_decisions(review_class);

COMMENT ON TABLE calyx_proposal_authorization_decisions IS
    'Immutable BUILD-BRAIN-114N repository-proposal review decisions. Records are digest-verified on read and grant no Git/GitHub mutation authority by themselves.';
