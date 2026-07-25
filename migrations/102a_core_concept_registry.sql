-- BUILD-SEM-002A: additive core concept identity registry.
-- This migration does not alter, delete, or deprecate any oc_ontology object.

CREATE SCHEMA IF NOT EXISTS oc_concepts;

CREATE TABLE IF NOT EXISTS oc_concepts.concept_schemes (
  scheme_id UUID PRIMARY KEY,
  scheme_key TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  authority TEXT NOT NULL,
  steward TEXT NOT NULL,
  review_state TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (review_state IN ('PENDING','IN_REVIEW','APPROVED','CHANGES_REQUESTED')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  revised_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_concepts.concept_releases (
  release_id UUID PRIMARY KEY,
  scheme_id UUID NOT NULL
    REFERENCES oc_concepts.concept_schemes(scheme_id),
  version TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT','ACTIVE','DEPRECATED')),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  revised_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (scheme_id, version)
);

CREATE TABLE IF NOT EXISTS oc_concepts.concepts (
  concept_id UUID PRIMARY KEY,
  concept_uri TEXT NOT NULL UNIQUE,
  scheme_id UUID NOT NULL
    REFERENCES oc_concepts.concept_schemes(scheme_id),
  release_id UUID REFERENCES oc_concepts.concept_releases(release_id),
  status TEXT NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT','ACTIVE','DEPRECATED','SUPERSEDED')),
  review_state TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (review_state IN ('PENDING','IN_REVIEW','APPROVED','CHANGES_REQUESTED')),
  steward TEXT NOT NULL,
  superseded_by_id UUID REFERENCES oc_concepts.concepts(concept_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  revised_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (
    concept_uri =
      'https://id.orchidcontinuum.org/concept/' || concept_id::text
  ),
  CHECK (
    (status = 'SUPERSEDED' AND superseded_by_id IS NOT NULL)
    OR (status <> 'SUPERSEDED' AND superseded_by_id IS NULL)
  ),
  CHECK (status <> 'ACTIVE' OR review_state = 'APPROVED'),
  CHECK (superseded_by_id IS NULL OR superseded_by_id <> concept_id)
);

CREATE TABLE IF NOT EXISTS oc_concepts.ontology_term_concepts (
  ontology_term_id BIGINT PRIMARY KEY
    REFERENCES oc_ontology.ontology_terms(id),
  concept_id UUID NOT NULL UNIQUE
    REFERENCES oc_concepts.concepts(concept_id),
  adapted_by TEXT NOT NULL,
  adapted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_concepts.concept_audit_events (
  event_id BIGSERIAL PRIMARY KEY,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  concept_id UUID NOT NULL
    REFERENCES oc_concepts.concepts(concept_id),
  resulting_state JSONB NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS concepts_scheme_status_idx
  ON oc_concepts.concepts(scheme_id, status);
CREATE INDEX IF NOT EXISTS concepts_release_idx
  ON oc_concepts.concepts(release_id);

CREATE OR REPLACE FUNCTION oc_concepts.enforce_concept_immutability()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'concepts cannot be deleted; deprecate or supersede instead';
  END IF;
  IF NEW.concept_id IS DISTINCT FROM OLD.concept_id
     OR NEW.concept_uri IS DISTINCT FROM OLD.concept_uri THEN
    RAISE EXCEPTION 'concept identity and URI are immutable';
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS concept_identity_immutable
  ON oc_concepts.concepts;
CREATE TRIGGER concept_identity_immutable
BEFORE UPDATE OR DELETE ON oc_concepts.concepts
FOR EACH ROW EXECUTE FUNCTION oc_concepts.enforce_concept_immutability();

CREATE OR REPLACE FUNCTION oc_concepts.enforce_concept_lifecycle()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE replacement_status TEXT;
DECLARE replacement_scheme UUID;
BEGIN
  IF NEW.status IS DISTINCT FROM OLD.status THEN
    IF NOT (
      (OLD.status = 'DRAFT' AND NEW.status IN ('ACTIVE','DEPRECATED'))
      OR (OLD.status = 'ACTIVE' AND NEW.status IN ('DEPRECATED','SUPERSEDED'))
      OR (OLD.status = 'DEPRECATED' AND NEW.status = 'SUPERSEDED')
    ) THEN
      RAISE EXCEPTION 'invalid concept lifecycle transition';
    END IF;
  END IF;
  IF NEW.status = 'SUPERSEDED' THEN
    SELECT status, scheme_id INTO replacement_status, replacement_scheme
    FROM oc_concepts.concepts
    WHERE concept_id = NEW.superseded_by_id;
    IF replacement_status IS DISTINCT FROM 'ACTIVE'
       OR replacement_scheme IS DISTINCT FROM NEW.scheme_id THEN
      RAISE EXCEPTION 'supersession requires an active concept in the same scheme';
    END IF;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS concept_lifecycle_valid
  ON oc_concepts.concepts;
CREATE TRIGGER concept_lifecycle_valid
BEFORE UPDATE ON oc_concepts.concepts
FOR EACH ROW EXECUTE FUNCTION oc_concepts.enforce_concept_lifecycle();

CREATE OR REPLACE FUNCTION oc_concepts.enforce_release_scheme()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE release_scheme UUID;
BEGIN
  IF NEW.release_id IS NOT NULL THEN
    SELECT scheme_id INTO release_scheme
    FROM oc_concepts.concept_releases
    WHERE release_id = NEW.release_id;
    IF release_scheme IS DISTINCT FROM NEW.scheme_id THEN
      RAISE EXCEPTION 'concept release belongs to another scheme';
    END IF;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS concept_release_scheme_valid
  ON oc_concepts.concepts;
CREATE TRIGGER concept_release_scheme_valid
BEFORE INSERT OR UPDATE ON oc_concepts.concepts
FOR EACH ROW EXECUTE FUNCTION oc_concepts.enforce_release_scheme();
