-- TRAITBANK-001: persistent store for oc-traitbank-v1 (Orchid-Continuum-Brain PR #246).
--
-- Append-only. A stored assertion is the original observation as its source
-- gave it (verbatim value, unit, citation, level); it is never edited in
-- place. Correction is a new assertion, not an UPDATE. Conflicting assertions
-- are all stored; conflicts are computed at read time, never collapsed here.
--
-- taxon_id is the canonical taxonomy id (public.orchid_taxonomy.id, the
-- taxonomy_id used by research traits, governed Matrix sources and KG taxon
-- nodes). Existence is enforced by the ingestion service at write time; it is
-- not a foreign key because the canonical taxonomy table is owned by another
-- lane and is not created by this migration.
--
-- Idempotent: safe to re-run.

BEGIN;

CREATE SCHEMA IF NOT EXISTS oc_traitbank;

CREATE TABLE IF NOT EXISTS oc_traitbank.trait_definitions (
    trait_id text PRIMARY KEY CHECK (trait_id ~ '^oc:trait:[a-z0-9_]{2,80}$'),
    label text NOT NULL,
    domain text NOT NULL,
    structure text NOT NULL,
    property text NOT NULL,
    value_kind text NOT NULL CHECK (value_kind IN ('quantitative', 'categorical')),
    unit text,
    oao_character_id text CHECK (oao_character_id IS NULL OR oao_character_id ~ '^OAO:[0-9]{7}$'),
    definition jsonb NOT NULL,
    definition_sha256 text NOT NULL CHECK (definition_sha256 ~ '^[0-9a-f]{64}$'),
    brain_contract_sha256 text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT trait_definition_unit CHECK (value_kind <> 'quantitative' OR unit IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS oc_traitbank.ingestion_batches (
    batch_pk bigserial PRIMARY KEY,
    batch_key text NOT NULL UNIQUE,
    payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    producer text NOT NULL CHECK (producer IN ('literature_extraction', 'eol_traitbank', 'curated')),
    contract_version text NOT NULL CHECK (contract_version = 'oc-traitbank-v1'),
    brain_contract_sha256 text NOT NULL,
    assertion_count integer NOT NULL CHECK (assertion_count >= 0),
    relation_count integer NOT NULL CHECK (relation_count >= 0),
    ingested_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS oc_traitbank.assertions (
    assertion_pk bigserial PRIMARY KEY,
    assertion_id text NOT NULL UNIQUE,
    batch_pk bigint NOT NULL REFERENCES oc_traitbank.ingestion_batches(batch_pk) ON DELETE RESTRICT,
    trait_id text NOT NULL REFERENCES oc_traitbank.trait_definitions(trait_id) ON DELETE RESTRICT,
    level text NOT NULL CHECK (level IN ('taxon', 'population', 'specimen', 'observation')),
    taxon_id bigint NOT NULL CHECK (taxon_id > 0),
    verbatim_taxon_name text NOT NULL,
    specimen_id text,
    population_id text,
    observation_id text,
    value_kind text NOT NULL CHECK (value_kind IN ('quantitative', 'range', 'categorical', 'missing')),
    numeric_value double precision,
    minimum_value double precision,
    maximum_value double precision,
    unit text,
    state_id text,
    statistic text NOT NULL,
    sd double precision CHECK (sd IS NULL OR sd >= 0),
    sample_size integer CHECK (sample_size IS NULL OR sample_size >= 0),
    uncertainty double precision CHECK (uncertainty IS NULL OR uncertainty >= 0),
    missing_reason text,
    verbatim_value text,
    evidence_state text NOT NULL CHECK (evidence_state IN (
        'AVAILABLE', 'PROVISIONAL', 'VERIFIED', 'CONTRADICTORY', 'UNKNOWN',
        'UNAVAILABLE', 'WITHHELD', 'ABSENT', 'REJECTED', 'SUPERSEDED')),
    scope_basis text NOT NULL CHECK (scope_basis IN ('source_reported', 'direct', 'aggregated_with_justification')),
    scope_justification text,
    derived_from text[] NOT NULL DEFAULT '{}',
    method_id text,
    -- NULL means the source reported no confidence. It is never defaulted.
    confidence numeric(6, 5) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    life_stage text,
    habitats text[] NOT NULL DEFAULT '{}',
    links jsonb NOT NULL DEFAULT '[]'::jsonb,
    notes text NOT NULL DEFAULT '',
    source_id text NOT NULL,
    source_kind text NOT NULL,
    original_record_id text NOT NULL,
    citation text NOT NULL CHECK (length(citation) > 0),
    license text NOT NULL CHECK (length(license) > 0),
    evidence_type text NOT NULL,
    contributor text,
    source_url text,
    locator text,
    original_text text,
    retrieved_at text,
    extraction_method text,
    review_status text NOT NULL,
    record_sha256 text NOT NULL CHECK (record_sha256 ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    -- One source record contributes one assertion per trait.
    CONSTRAINT traitbank_source_record_unique UNIQUE (source_id, original_record_id, trait_id),
    CONSTRAINT traitbank_level_subject CHECK (
        (level <> 'specimen' OR specimen_id IS NOT NULL)
        AND (level <> 'population' OR population_id IS NOT NULL)
        AND (level <> 'observation' OR observation_id IS NOT NULL)
        AND (level <> 'taxon' OR scope_basis <> 'direct')
        AND (scope_basis <> 'aggregated_with_justification'
             OR (scope_justification IS NOT NULL AND cardinality(derived_from) > 0))
    ),
    CONSTRAINT traitbank_value_shape CHECK (
        (value_kind = 'quantitative' AND numeric_value IS NOT NULL AND unit IS NOT NULL)
        OR (value_kind = 'range' AND minimum_value IS NOT NULL AND maximum_value IS NOT NULL
            AND minimum_value <= maximum_value AND unit IS NOT NULL)
        OR (value_kind = 'categorical' AND state_id IS NOT NULL)
        OR (value_kind = 'missing' AND missing_reason IS NOT NULL AND numeric_value IS NULL
            AND state_id IS NULL AND evidence_state IN ('UNKNOWN', 'UNAVAILABLE', 'WITHHELD', 'ABSENT'))
    ),
    CONSTRAINT traitbank_verified_is_reviewed CHECK (
        evidence_state <> 'VERIFIED' OR review_status IN ('accepted', 'corrected')
    )
);

CREATE INDEX IF NOT EXISTS traitbank_assertions_taxon ON oc_traitbank.assertions (taxon_id, trait_id);
CREATE INDEX IF NOT EXISTS traitbank_assertions_trait ON oc_traitbank.assertions (trait_id);
CREATE INDEX IF NOT EXISTS traitbank_assertions_source ON oc_traitbank.assertions (source_id);

CREATE TABLE IF NOT EXISTS oc_traitbank.environment_relations (
    relation_pk bigserial PRIMARY KEY,
    relation_id text NOT NULL UNIQUE,
    batch_pk bigint NOT NULL REFERENCES oc_traitbank.ingestion_batches(batch_pk) ON DELETE RESTRICT,
    trait_id text NOT NULL REFERENCES oc_traitbank.trait_definitions(trait_id) ON DELETE RESTRICT,
    environment_variable text NOT NULL,
    claim_kind text NOT NULL CHECK (claim_kind IN ('observed_correlation', 'proposed_hypothesis', 'tested_hypothesis')),
    statement text NOT NULL,
    taxon_scope bigint[] NOT NULL DEFAULT '{}',
    direction text,
    effect_size text,
    sample_size integer CHECK (sample_size IS NULL OR sample_size >= 0),
    hypothesis_scope text,
    test_design text,
    test_outcome text,
    source_id text NOT NULL,
    original_record_id text NOT NULL,
    citation text NOT NULL,
    license text NOT NULL,
    evidence_type text NOT NULL,
    locator text,
    original_text text,
    record_sha256 text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT traitbank_relation_kind CHECK (
        (claim_kind = 'observed_correlation' AND hypothesis_scope IS NULL AND test_outcome IS NULL)
        OR (claim_kind = 'proposed_hypothesis' AND hypothesis_scope IS NOT NULL AND test_outcome IS NULL)
        OR (claim_kind = 'tested_hypothesis' AND hypothesis_scope IS NOT NULL
            AND test_design IS NOT NULL AND test_outcome IN ('supported', 'not_supported', 'inconclusive'))
    )
);

CREATE INDEX IF NOT EXISTS traitbank_relations_trait ON oc_traitbank.environment_relations (trait_id);

-- Append-only: originals are preserved by refusing UPDATE and DELETE.
CREATE OR REPLACE FUNCTION oc_traitbank.refuse_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'TRAITBANK_APPEND_ONLY: % on %.% is not permitted', TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END;
$$;

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['assertions', 'environment_relations', 'ingestion_batches', 'trait_definitions'] LOOP
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
