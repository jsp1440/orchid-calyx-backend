-- OWNER-APPLIED rollback for 20261011_atlas_public_occurrences_v1.sql.
-- Removes only the projection; public.orchid_occurrence and public.orchid_taxonomy
-- are never modified by the apply script, so nothing else needs restoring.
-- Unset ATLAS_OCCURRENCE_RELATION first; the Atlas API then reports
-- source_not_configured instead of failing.
BEGIN;
DROP MATERIALIZED VIEW IF EXISTS oc_atlas.public_occurrences_v1;
COMMIT;
