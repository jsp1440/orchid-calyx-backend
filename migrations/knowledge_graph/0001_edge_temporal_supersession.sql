-- Migration: temporal validity + supersession metadata for graph edges
-- Target schema: oc_graph
-- Status: GENERATED ONLY — NOT EXECUTED against production by this change.
-- Safety: idempotent (IF NOT EXISTS), additive-only, no data rewrite, no drops.
--
-- WHY THIS IS NEEDED
-- The scientific graph must be able to preserve, per edge:
--   * valid-from / valid-to  (temporal validity of a relationship)
--   * supersession           (a newer assertion replacing an older one)
--   * relationship status    (active / superseded / retracted)
-- The current oc_graph.kg_edges table records provenance (source_table,
-- source_pk), evidence_class and confidence, plus created_at/updated_at, but
-- has no first-class temporal-validity or supersession columns. Evidence and
-- contradiction can already be modelled as assertion/evidence nodes + edges
-- (has_trait -> supported_by_evidence / contradicted_by), so only the temporal
-- and supersession fields require schema support.
--
-- Taxonomy-only edges do not use these columns; they default to NULL/'active'
-- and remain valid. Columns are optional so existing builds are unaffected.

ALTER TABLE oc_graph.kg_edges
    ADD COLUMN IF NOT EXISTS valid_from      timestamptz,
    ADD COLUMN IF NOT EXISTS valid_to        timestamptz,
    ADD COLUMN IF NOT EXISTS relationship_status text NOT NULL DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS superseded_by_edge_id bigint;

-- Optional self-reference so a superseding edge can be traversed. Guarded so
-- re-runs do not error if the constraint already exists.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'kg_edges_superseded_by_fk'
    ) THEN
        ALTER TABLE oc_graph.kg_edges
            ADD CONSTRAINT kg_edges_superseded_by_fk
            FOREIGN KEY (superseded_by_edge_id)
            REFERENCES oc_graph.kg_edges (kg_edge_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS kg_edges_status_idx
    ON oc_graph.kg_edges (relationship_status);

-- ROLLBACK GUIDANCE (run manually only if reverting; safe, additive removal):
--   ALTER TABLE oc_graph.kg_edges DROP CONSTRAINT IF EXISTS kg_edges_superseded_by_fk;
--   DROP INDEX IF EXISTS oc_graph.kg_edges_status_idx;
--   ALTER TABLE oc_graph.kg_edges
--     DROP COLUMN IF EXISTS superseded_by_edge_id,
--     DROP COLUMN IF EXISTS relationship_status,
--     DROP COLUMN IF EXISTS valid_to,
--     DROP COLUMN IF EXISTS valid_from;
