-- BUILD-086E / CALYX-SPEAK production repair
-- Extend the existing runtime snapshot persistence contract to the semantic index.
-- Additive constraint repair only; no data reset, truncate, publication, or graph mutation.

CREATE SCHEMA IF NOT EXISTS oc_candidate_knowledge;

DO $$
DECLARE
    constraint_name text;
BEGIN
    SELECT c.conname
      INTO constraint_name
      FROM pg_constraint c
      JOIN pg_class t ON t.oid = c.conrelid
      JOIN pg_namespace n ON n.oid = t.relnamespace
     WHERE n.nspname = 'oc_candidate_knowledge'
       AND t.relname = 'runtime_repository_snapshots'
       AND c.contype = 'c'
       AND pg_get_constraintdef(c.oid) LIKE '%repository_kind%'
     LIMIT 1;

    IF constraint_name IS NOT NULL THEN
        EXECUTE format(
            'ALTER TABLE oc_candidate_knowledge.runtime_repository_snapshots DROP CONSTRAINT %I',
            constraint_name
        );
    END IF;
END $$;

ALTER TABLE oc_candidate_knowledge.runtime_repository_snapshots
    ADD CONSTRAINT runtime_repository_snapshots_repository_kind_check
    CHECK (repository_kind IN (
        'candidate_knowledge',
        'evidence_aggregation',
        'semantic_index'
    ));

COMMENT ON CONSTRAINT runtime_repository_snapshots_repository_kind_check
ON oc_candidate_knowledge.runtime_repository_snapshots IS
'Permitted governed runtime snapshot repositories; semantic_index added by BUILD-086E.';
