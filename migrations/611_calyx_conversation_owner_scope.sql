BEGIN;

ALTER TABLE IF EXISTS calyx_conversations
    ADD COLUMN IF NOT EXISTS owner TEXT;

ALTER TABLE IF EXISTS calyx_conversations
    ADD COLUMN IF NOT EXISTS project_id TEXT;

UPDATE calyx_conversations
SET owner = 'legacy-owner'
WHERE owner IS NULL;

ALTER TABLE IF EXISTS calyx_conversations
    ALTER COLUMN owner SET NOT NULL;

ALTER TABLE IF EXISTS calyx_conversation_messages
    ADD COLUMN IF NOT EXISTS content_hash TEXT;

UPDATE calyx_conversation_messages
SET content_hash = 'legacy-unhashed:' || message_id::text
WHERE content_hash IS NULL;

ALTER TABLE IF EXISTS calyx_conversation_messages
    ALTER COLUMN content_hash SET NOT NULL;

ALTER TABLE IF EXISTS calyx_conversation_messages
    DROP CONSTRAINT IF EXISTS calyx_conversation_messages_role_check;

ALTER TABLE IF EXISTS calyx_conversation_messages
    ADD CONSTRAINT calyx_conversation_messages_role_check
    CHECK (role IN ('operator','calyx','system','tool'));

CREATE INDEX IF NOT EXISTS idx_calyx_conversations_owner_updated
    ON calyx_conversations(owner, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_calyx_conversations_owner_project
    ON calyx_conversations(owner, project_id, updated_at DESC);

COMMIT;
