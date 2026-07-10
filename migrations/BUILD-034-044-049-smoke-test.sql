-- BUILD-034/044/049 production smoke test.
-- Run after applying the BUILD-034, BUILD-044, and BUILD-049 migrations.
-- This file is read-only except for the transaction wrapper and is safe to rollback.

\set ON_ERROR_STOP on

BEGIN;

DO $$
BEGIN
    IF to_regclass('oc_governance.decision_ledger') IS NULL THEN
        RAISE EXCEPTION 'Missing BUILD-034 table: oc_governance.decision_ledger';
    END IF;
    IF to_regclass('oc_admin.calyx_agents') IS NULL THEN
        RAISE EXCEPTION 'Missing BUILD-044 table: oc_admin.calyx_agents';
    END IF;
    IF to_regclass('oc_admin.calyx_tasks') IS NULL THEN
        RAISE EXCEPTION 'Missing BUILD-044 table: oc_admin.calyx_tasks';
    END IF;
    IF to_regclass('oc_admin.harvester_registry') IS NULL THEN
        RAISE EXCEPTION 'Missing BUILD-049 table: oc_admin.harvester_registry';
    END IF;
    IF to_regclass('oc_admin.harvester_runs') IS NULL THEN
        RAISE EXCEPTION 'Missing BUILD-049 table: oc_admin.harvester_runs';
    END IF;
    IF to_regclass('oc_admin.harvester_target_proposals') IS NULL THEN
        RAISE EXCEPTION 'Missing BUILD-049 table: oc_admin.harvester_target_proposals';
    END IF;
END $$;

SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_schema = 'oc_admin'
  AND table_name IN (
      'calyx_agents',
      'calyx_tasks',
      'calyx_observations',
      'calyx_runs',
      'harvester_registry',
      'harvester_runs',
      'harvester_target_proposals'
  )
ORDER BY table_name;

SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_schema = 'oc_governance'
  AND table_name IN (
      'missions',
      'policies',
      'decision_ledger',
      'governance_questions',
      'checkpoints'
  )
ORDER BY table_name;

SELECT indexname
FROM pg_indexes
WHERE schemaname = 'oc_admin'
  AND tablename IN ('calyx_tasks', 'harvester_registry', 'harvester_runs', 'harvester_target_proposals')
ORDER BY tablename, indexname;

SELECT task_type, status, COUNT(*) AS task_count
FROM oc_admin.calyx_tasks
GROUP BY task_type, status
ORDER BY task_type, status;

SELECT harvester_id, operational_state, enabled
FROM oc_admin.harvester_registry
ORDER BY harvester_id;

ROLLBACK;
