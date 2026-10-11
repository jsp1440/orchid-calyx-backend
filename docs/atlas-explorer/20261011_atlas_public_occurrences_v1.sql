-- OWNER-APPLIED. Not run by any job, migration runner, or agent.
--
-- ATLAS-EXPLORER-001: Atlas occurrence projection over public.orchid_occurrence.
--
-- Creates oc_atlas.public_occurrences_v1, a materialized view that satisfies the
-- Atlas projection column contract in app/atlas_intelligence/README.md, so that
-- ATLAS_OCCURRENCE_RELATION=oc_atlas.public_occurrences_v1 can be configured.
--
-- Source evidence (docs/evidence/audit-measurement-002/integration-gap-diagnostic.json,
-- read-only, 2026-08-18): public.orchid_occurrence holds 580,612 rows; every
-- non-null taxonomy_id (109,195) resolves into public.orchid_taxonomy.id.
-- Run scripts/diagnose_atlas_occurrence_projection.py first and record its
-- output; the decisions below are only as good as that evidence.
--
-- What this view does:
--   * Serves only rows linked to the canonical orchid backbone
--     (public.orchid_taxonomy) with usable coordinates.
--   * family = the family the source record states in raw_payload; when the
--     record states none, 'Orchidaceae' on the basis of the orchid backbone
--     link (family_basis records which). A record that states any other family
--     (e.g. Hypoxis, Hypoxidaceae) keeps that family and is therefore never
--     served: the Atlas service serves only family = 'Orchidaceae'.
--   * Darwin Core terms (licence, dataset, basis of record, uncertainty,
--     institution, rights holder, country code) come from raw_payload when the
--     record carries them, and are NULL otherwise. Nothing is invented.
--   * No conservation join: oc_conservation.conservation_records holds 2 rows, so
--     every row is assessment_resolved = false and the public API generalises it
--     to at least a 0.05 degree cell. Wire a conservation source only after the
--     owner approves one.
--   * occurrence_id is the internal surrogate bigint, never a provider key.
--
-- Privacy: the view holds precise coordinates, exactly like its source. It is
-- read only by the Calyx backend, which generalises before serving. No grant to
-- PUBLIC, anon, or authenticated roles is made here.

BEGIN;

DO $$
BEGIN
  IF to_regclass('public.orchid_occurrence') IS NULL THEN
    RAISE EXCEPTION 'precondition: public.orchid_occurrence is missing';
  END IF;
  IF to_regclass('public.orchid_taxonomy') IS NULL THEN
    RAISE EXCEPTION 'precondition: public.orchid_taxonomy is missing';
  END IF;
  IF (
    SELECT count(*) FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'orchid_occurrence'
      AND column_name IN ('occurrence_id', 'taxonomy_id', 'decimal_latitude', 'decimal_longitude',
                          'raw_payload', 'locality', 'event_year', 'event_month',
                          'event_date_standardized', 'canonical_gbif_occurrence_key',
                          'source_table', 'source_record_id', 'canonical_name_clean', 'canonical_name',
                          'scientific_name')
  ) <> 15 THEN
    RAISE EXCEPTION 'precondition: public.orchid_occurrence lacks a column this projection reads';
  END IF;
  IF (
    SELECT count(*) FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'orchid_taxonomy'
      AND column_name IN ('id', 'scientific_name', 'genus')
  ) <> 3 THEN
    RAISE EXCEPTION 'precondition: public.orchid_taxonomy lacks id, scientific_name or genus';
  END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS oc_atlas;

DROP MATERIALIZED VIEW IF EXISTS oc_atlas.public_occurrences_v1;

CREATE MATERIALIZED VIEW oc_atlas.public_occurrences_v1 AS
WITH src AS (
  SELECT
    o.*,
    t.id::text AS canonical_taxon_id,
    t.genus AS canonical_genus,
    t.scientific_name AS canonical_scientific_name,
    NULLIF(btrim(o.raw_payload ->> 'family'), '') AS stated_family
  FROM public.orchid_occurrence o
  JOIN public.orchid_taxonomy t ON t.id = o.taxonomy_id
  WHERE o.decimal_latitude IS NOT NULL
    AND o.decimal_longitude IS NOT NULL
    AND o.decimal_latitude BETWEEN -90 AND 90
    AND o.decimal_longitude BETWEEN -180 AND 180
    AND NOT (o.decimal_latitude = 0 AND o.decimal_longitude = 0)
)
SELECT
  src.occurrence_id::text AS occurrence_id,
  src.canonical_taxon_id AS taxon_id,
  COALESCE(NULLIF(btrim(src.canonical_name_clean), ''),
           NULLIF(btrim(src.canonical_name), ''),
           src.canonical_scientific_name) AS scientific_name,
  COALESCE(NULLIF(btrim(src.canonical_genus), ''),
           split_part(COALESCE(src.canonical_name_clean, src.canonical_scientific_name), ' ', 1)) AS genus,
  src.decimal_latitude,
  src.decimal_longitude,
  CASE WHEN src.raw_payload ->> 'coordinateUncertaintyInMeters' ~ '^[0-9]+(\.[0-9]+)?$'
       THEN (src.raw_payload ->> 'coordinateUncertaintyInMeters')::double precision END
    AS coordinate_uncertainty_in_meters,
  CASE WHEN src.raw_payload ->> 'countryCode' ~ '^[A-Z]{2}$'
       THEN src.raw_payload ->> 'countryCode' END AS country_code,
  src.event_year AS year,
  CASE WHEN src.event_month BETWEEN 1 AND 12 THEN src.event_month END AS month,
  src.event_date_standardized::text AS event_date,
  NULLIF(btrim(src.raw_payload ->> 'basisOfRecord'), '') AS basis_of_record,
  COALESCE(NULLIF(btrim(src.raw_payload ->> 'datasetName'), ''), src.source_table) AS dataset_name,
  NULLIF(btrim(src.raw_payload ->> 'institutionCode'), '') AS institution_code,
  NULLIF(btrim(src.raw_payload ->> 'license'), '') AS license,
  NULLIF(btrim(src.raw_payload ->> 'rightsHolder'), '') AS rights_holder,
  CASE WHEN src.canonical_gbif_occurrence_key IS NOT NULL
       THEN 'https://www.gbif.org/occurrence/' || src.canonical_gbif_occurrence_key END AS references_uri,
  NULL::text AS iucn_category,
  NULL::text AS conservation_status,
  false AS assessment_resolved,
  src.locality,
  COALESCE(src.stated_family, 'Orchidaceae') AS family,
  CASE WHEN src.stated_family IS NULL THEN 'orchid_backbone_link' ELSE 'source_stated' END AS family_basis,
  src.source_table,
  src.source_record_id::text AS source_record_id
FROM src;

CREATE UNIQUE INDEX public_occurrences_v1_occurrence_id ON oc_atlas.public_occurrences_v1 (occurrence_id);
CREATE INDEX public_occurrences_v1_lat_lng ON oc_atlas.public_occurrences_v1 (decimal_latitude, decimal_longitude);
CREATE INDEX public_occurrences_v1_taxon ON oc_atlas.public_occurrences_v1 (taxon_id);
CREATE INDEX public_occurrences_v1_family_genus ON oc_atlas.public_occurrences_v1 (family, genus);

REVOKE ALL ON oc_atlas.public_occurrences_v1 FROM PUBLIC;

COMMENT ON MATERIALIZED VIEW oc_atlas.public_occurrences_v1 IS
  'ATLAS-EXPLORER-001 projection of public.orchid_occurrence for the Calyx Atlas API. '
  'Precise coordinates: backend-only; the API generalises before serving. '
  'Refresh with REFRESH MATERIALIZED VIEW CONCURRENTLY.';

COMMIT;
