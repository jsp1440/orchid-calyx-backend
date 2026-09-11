-- Rollback for CALYX-EVOLVE-001 experiment ledger.
--
-- Drops only the seven tables the forward migration created. The oc_admin
-- schema is left in place because other BUILD migrations own tables inside it.
-- Nothing outside oc_admin.calyx_evolve_* is touched.
\set ON_ERROR_STOP on

BEGIN;

DROP TABLE IF EXISTS oc_admin.calyx_evolve_promotion_proposals;
DROP TABLE IF EXISTS oc_admin.calyx_evolve_findings;
DROP TABLE IF EXISTS oc_admin.calyx_evolve_metrics;
DROP TABLE IF EXISTS oc_admin.calyx_evolve_runs;
DROP TABLE IF EXISTS oc_admin.calyx_evolve_candidates;
DROP TABLE IF EXISTS oc_admin.calyx_evolve_cognition_items;
DROP TABLE IF EXISTS oc_admin.calyx_evolve_campaigns;

COMMIT;
