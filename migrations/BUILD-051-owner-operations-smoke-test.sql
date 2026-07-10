-- BUILD-051 post-migration smoke test. Read-only and rollback-safe.
\set ON_ERROR_STOP on

BEGIN;

DO $$
BEGIN
    IF to_regclass('oc_admin.build051_source_briefings') IS NULL THEN
        RAISE EXCEPTION 'Missing oc_admin.build051_source_briefings';
    END IF;
    IF to_regclass('oc_admin.build051_intelligence_items') IS NULL THEN
        RAISE EXCEPTION 'Missing oc_admin.build051_intelligence_items';
    END IF;
    IF to_regclass('oc_admin.build051_owner_commands') IS NULL THEN
        RAISE EXCEPTION 'Missing oc_admin.build051_owner_commands';
    END IF;
    IF to_regclass('oc_admin.build051_operations_queue') IS NULL THEN
        RAISE EXCEPTION 'Missing oc_admin.build051_operations_queue';
    END IF;
    IF to_regclass('oc_admin.build051_research_requests') IS NULL THEN
        RAISE EXCEPTION 'Missing oc_admin.build051_research_requests';
    END IF;
    IF to_regclass('oc_admin.build051_generated_audits') IS NULL THEN
        RAISE EXCEPTION 'Missing oc_admin.build051_generated_audits';
    END IF;
    IF to_regclass('oc_admin.build051_partnership_packets') IS NULL THEN
        RAISE EXCEPTION 'Missing oc_admin.build051_partnership_packets';
    END IF;
    IF to_regclass('oc_admin.build051_privileged_action_log') IS NULL THEN
        RAISE EXCEPTION 'Missing oc_admin.build051_privileged_action_log';
    END IF;
END $$;

SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'oc_admin'
  AND table_name LIKE 'build051_%'
ORDER BY table_name;

SELECT tablename, indexname
FROM pg_indexes
WHERE schemaname = 'oc_admin'
  AND tablename LIKE 'build051_%'
ORDER BY tablename, indexname;

SELECT COUNT(*) AS action_log_rows
FROM oc_admin.build051_privileged_action_log;

ROLLBACK;
