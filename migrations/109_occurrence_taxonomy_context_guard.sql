-- CALYX CORE 2 corrective guard: occurrence reconciliation may bind only to a
-- completely staged taxonomy release. Additive and staging-only.

CREATE OR REPLACE FUNCTION occurrence_pipeline.guard_taxonomy_context()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    release_state text;
    release_sha text;
    staging_complete boolean;
BEGIN
    SELECT r.state, r.source_sha256
      INTO release_state, release_sha
      FROM taxonomy_pipeline.releases r
     WHERE r.release_id = NEW.taxonomy_release_id;

    IF release_state IS NULL THEN
        RAISE EXCEPTION 'TAXONOMY_RELEASE_NOT_FOUND';
    END IF;

    IF release_state NOT IN ('staged', 'review_required', 'reviewed') THEN
        RAISE EXCEPTION 'TAXONOMY_RELEASE_NOT_READY:%', release_state;
    END IF;

    SELECT c.completed
      INTO staging_complete
      FROM taxonomy_pipeline.staging_checkpoints c
     WHERE c.release_id = NEW.taxonomy_release_id;

    IF staging_complete IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'TAXONOMY_STAGING_INCOMPLETE';
    END IF;

    IF NEW.taxonomy_source_sha256 <> release_sha THEN
        RAISE EXCEPTION 'TAXONOMY_SOURCE_SHA_MISMATCH';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_occurrence_guard_taxonomy_context
    ON occurrence_pipeline.reconciliation_runs;
CREATE TRIGGER trg_occurrence_guard_taxonomy_context
BEFORE INSERT OR UPDATE OF taxonomy_release_id, taxonomy_source_sha256
ON occurrence_pipeline.reconciliation_runs
FOR EACH ROW
EXECUTE FUNCTION occurrence_pipeline.guard_taxonomy_context();
