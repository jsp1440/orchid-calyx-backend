-- CALYX multimodal intelligence persistence schema.
-- This migration is intentionally not activated by this PR.
-- Applying it requires the existing governed migration approval path.

CREATE TABLE IF NOT EXISTS calyx_multimodal_operations (
    operation_id UUID PRIMARY KEY,
    operation_type TEXT NOT NULL,
    request_hash TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    result JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    provenance JSONB NOT NULL,
    human_review_required BOOLEAN NOT NULL DEFAULT TRUE,
    review JSONB,
    errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    CONSTRAINT calyx_multimodal_operation_type_nonempty CHECK (length(trim(operation_type)) > 0),
    CONSTRAINT calyx_multimodal_request_hash_nonempty CHECK (length(trim(request_hash)) > 0)
);

CREATE INDEX IF NOT EXISTS ix_calyx_multimodal_operations_review_queue
    ON calyx_multimodal_operations (human_review_required, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_calyx_multimodal_operations_type_state
    ON calyx_multimodal_operations (operation_type, state, created_at DESC);

COMMENT ON TABLE calyx_multimodal_operations IS
    'Governed Literature/Matrix/Vision operation records; no automatic publication or graph mutation.';
