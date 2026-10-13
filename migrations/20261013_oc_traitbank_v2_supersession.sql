-- TRAITBANK-002: supersession and evidence crosswalk for oc_traitbank.
--
-- Requires 20261011_oc_traitbank_v1.sql. Idempotent: safe to re-run.
--
-- Supersession never edits or deletes the superseded assertion. It is a
-- separate, append-only decision record naming the original, the reason, the
-- reviewer reference and (except for a retraction) the assertion that
-- replaces it. Reads compute the effective state; the stored original keeps
-- its value, citation, level and evidence state exactly as ingested.
--
-- A record can be superseded at most once (UNIQUE superseded_assertion_id),
-- and a successor must itself be current when the decision is recorded
-- (enforced by the repository inside the same transaction), so chains are
-- linear and cannot loop.

BEGIN;

CREATE TABLE IF NOT EXISTS oc_traitbank.assertion_supersessions (
    supersession_pk bigserial PRIMARY KEY,
    superseded_assertion_id text NOT NULL UNIQUE
        REFERENCES oc_traitbank.assertions(assertion_id) ON DELETE RESTRICT,
    superseding_assertion_id text
        REFERENCES oc_traitbank.assertions(assertion_id) ON DELETE RESTRICT,
    kind text NOT NULL CHECK (kind IN (
        'corrected',          -- same subject, value or provenance corrected
        'reidentified',       -- the organism was a different taxon
        'reanalysed',         -- same observation, new analysis or method
        'duplicate_of',       -- the same source record ingested twice
        'retracted'           -- withdrawn by the source or a reviewer; no successor
    )),
    reason text NOT NULL CHECK (length(btrim(reason)) >= 10),
    review_reference text NOT NULL CHECK (length(btrim(review_reference)) > 0),
    decided_by text NOT NULL CHECK (length(btrim(decided_by)) > 0),
    record_sha256 text NOT NULL CHECK (record_sha256 ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT supersession_not_self CHECK (superseding_assertion_id IS DISTINCT FROM superseded_assertion_id),
    CONSTRAINT supersession_successor_rule CHECK (
        (kind = 'retracted' AND superseding_assertion_id IS NULL)
        OR (kind <> 'retracted' AND superseding_assertion_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS traitbank_supersessions_successor
    ON oc_traitbank.assertion_supersessions (superseding_assertion_id);

-- Deterministic identifiers shared with the Knowledge Graph publisher (#901)
-- and graph-grounded reasoning (#1819). Written once at ingestion.
CREATE TABLE IF NOT EXISTS oc_traitbank.evidence_crosswalk (
    assertion_id text PRIMARY KEY
        REFERENCES oc_traitbank.assertions(assertion_id) ON DELETE RESTRICT,
    source_record_kind text NOT NULL CHECK (source_record_kind IN ('measurement', 'claim', 'dataset_record', 'curated')),
    kg_object_key text,
    source_document_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['assertion_supersessions', 'evidence_crosswalk'] LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger
            WHERE tgname = 'traitbank_append_only'
              AND tgrelid = format('oc_traitbank.%I', t)::regclass
        ) THEN
            EXECUTE format(
                'CREATE TRIGGER traitbank_append_only BEFORE UPDATE OR DELETE ON oc_traitbank.%I '
                'FOR EACH ROW EXECUTE FUNCTION oc_traitbank.refuse_mutation()', t);
        END IF;
    END LOOP;
END;
$$;

COMMIT;
