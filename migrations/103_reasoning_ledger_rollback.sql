BEGIN;

DROP TABLE IF EXISTS reasoning_ledger.audit_events;
DROP TABLE IF EXISTS reasoning_ledger.ledger_revisions;
DROP TABLE IF EXISTS reasoning_ledger.ledger_heads;
DROP SCHEMA IF EXISTS reasoning_ledger;

COMMIT;
