-- BUILD-077 additive ontology and evidence registry.
-- Migration order: 076a_universal_intake.sql, 076b_semantic_extraction.sql, then this file.
CREATE SCHEMA IF NOT EXISTS oc_ontology;

CREATE TABLE IF NOT EXISTS oc_ontology.ontology_registries (
  id BIGSERIAL PRIMARY KEY, namespace TEXT NOT NULL, name TEXT NOT NULL, description TEXT,
  authority TEXT NOT NULL, source_uri TEXT, version TEXT NOT NULL, ontology_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','ACTIVE','DEPRECATED','RETIRED')),
  checksum CHAR(64) NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'), provenance JSONB NOT NULL,
  created_by TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(namespace, version), CHECK (ontology_type IN ('TAXONOMY','GLOSSARY','TRAIT','HABITAT','POLLINATOR','MYCORRHIZA','GEOGRAPHY','ORGANIZATION','PERSON','LITERATURE','MEDIA','CONSERVATION'))
);

CREATE TABLE IF NOT EXISTS oc_ontology.ontology_terms (
  id BIGSERIAL PRIMARY KEY, registry_id BIGINT NOT NULL REFERENCES oc_ontology.ontology_registries(id),
  canonical_key TEXT NOT NULL, preferred_label TEXT NOT NULL, normalized_label TEXT NOT NULL, definition TEXT,
  term_type TEXT NOT NULL, parent_term_id BIGINT REFERENCES oc_ontology.ontology_terms(id), external_ids JSONB NOT NULL DEFAULT '{}'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb, status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','ACTIVE','DEPRECATED')),
  replacement_term_id BIGINT REFERENCES oc_ontology.ontology_terms(id), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(registry_id, canonical_key), CHECK (parent_term_id IS NULL OR parent_term_id <> id),
  CHECK (replacement_term_id IS NULL OR replacement_term_id <> id), CHECK (status <> 'DEPRECATED' OR replacement_term_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS oc_ontology.ontology_synonyms (
  id BIGSERIAL PRIMARY KEY, term_id BIGINT NOT NULL REFERENCES oc_ontology.ontology_terms(id) ON DELETE CASCADE,
  synonym TEXT NOT NULL, normalized_synonym TEXT NOT NULL,
  synonym_type TEXT NOT NULL CHECK (synonym_type IN ('EXACT','ALTERNATE','HISTORICAL','ABBREVIATION','MISSPELLING','SCIENTIFIC_NAME','COMMON_NAME')),
  provenance JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(term_id, normalized_synonym, synonym_type)
);

CREATE TABLE IF NOT EXISTS oc_ontology.candidate_resolutions (
  id BIGSERIAL PRIMARY KEY, candidate_id BIGINT NOT NULL REFERENCES oc_semantic.candidates(id) ON DELETE CASCADE,
  ontology_term_id BIGINT REFERENCES oc_ontology.ontology_terms(id),
  resolution_method TEXT NOT NULL CHECK (resolution_method IN ('EXACT','NORMALIZED','SYNONYM','FUZZY','MANUAL','UNRESOLVED')),
  confidence DOUBLE PRECISION NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  status TEXT NOT NULL CHECK (status IN ('PROPOSED','ACCEPTED','REJECTED','NEEDS_REVIEW')),
  normalized_input TEXT NOT NULL, matched_label TEXT, ontology_namespace TEXT, ontology_version TEXT,
  explanation JSONB NOT NULL, provenance JSONB NOT NULL, resolved_by TEXT, resolved_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (resolution_method <> 'UNRESOLVED' OR ontology_term_id IS NULL),
  CHECK (status <> 'ACCEPTED' OR ontology_term_id IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS ontology_one_accepted_resolution_idx ON oc_ontology.candidate_resolutions(candidate_id) WHERE status='ACCEPTED';

CREATE TABLE IF NOT EXISTS oc_ontology.evidence_registry (
  id BIGSERIAL PRIMARY KEY, evidence_object_id BIGINT NOT NULL UNIQUE REFERENCES oc_semantic.evidence_objects(id),
  evidence_hash CHAR(64) NOT NULL, source_document_id BIGINT NOT NULL REFERENCES oc_intake.documents(id), source_sha256 CHAR(64) NOT NULL,
  validation_status TEXT NOT NULL CHECK (validation_status IN ('PENDING','VALID','INVALID','SUPERSEDED')),
  validation_details JSONB NOT NULL DEFAULT '{}'::jsonb, validator_version TEXT NOT NULL, registered_by TEXT NOT NULL,
  registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), last_validated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS oc_ontology.publication_readiness (
  id BIGSERIAL PRIMARY KEY, candidate_id BIGINT NOT NULL REFERENCES oc_semantic.candidates(id) ON DELETE CASCADE,
  evidence_complete BOOLEAN NOT NULL, ontology_resolved BOOLEAN NOT NULL, review_complete BOOLEAN NOT NULL,
  provenance_complete BOOLEAN NOT NULL, ready_for_publication BOOLEAN NOT NULL, blockers JSONB NOT NULL,
  evaluated_by TEXT NOT NULL, evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), evaluation_version TEXT NOT NULL, is_current BOOLEAN NOT NULL DEFAULT TRUE,
  CHECK (NOT ready_for_publication OR (evidence_complete AND ontology_resolved AND review_complete AND provenance_complete AND blockers='[]'::jsonb))
);
CREATE UNIQUE INDEX IF NOT EXISTS ontology_current_readiness_idx ON oc_ontology.publication_readiness(candidate_id) WHERE is_current;

CREATE TABLE IF NOT EXISTS oc_ontology.ontology_audit_events (
  id BIGSERIAL PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL, target_type TEXT NOT NULL,
  target_id BIGINT NOT NULL, previous_state JSONB, resulting_state JSONB, reason TEXT,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ontology_terms_lookup_idx ON oc_ontology.ontology_terms(registry_id, normalized_label);
CREATE INDEX IF NOT EXISTS ontology_synonyms_lookup_idx ON oc_ontology.ontology_synonyms(normalized_synonym);
CREATE INDEX IF NOT EXISTS ontology_resolution_candidate_idx ON oc_ontology.candidate_resolutions(candidate_id, status);
CREATE INDEX IF NOT EXISTS ontology_audit_target_idx ON oc_ontology.ontology_audit_events(target_type, target_id, occurred_at);

CREATE OR REPLACE FUNCTION oc_ontology.enforce_registry_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status <> 'DRAFT' AND (NEW.namespace,NEW.version,NEW.checksum) IS DISTINCT FROM (OLD.namespace,OLD.version,OLD.checksum) THEN
    RAISE EXCEPTION 'activated ontology identity is immutable';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS ontology_registry_identity_immutable ON oc_ontology.ontology_registries;
CREATE TRIGGER ontology_registry_identity_immutable BEFORE UPDATE ON oc_ontology.ontology_registries FOR EACH ROW EXECUTE FUNCTION oc_ontology.enforce_registry_identity();

CREATE OR REPLACE FUNCTION oc_ontology.enforce_term_links() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE linked_registry BIGINT;
BEGIN
  IF NEW.parent_term_id IS NOT NULL THEN
    SELECT registry_id INTO linked_registry FROM oc_ontology.ontology_terms WHERE id=NEW.parent_term_id;
    IF linked_registry IS DISTINCT FROM NEW.registry_id THEN RAISE EXCEPTION 'parent term belongs to another registry'; END IF;
  END IF;
  IF NEW.replacement_term_id IS NOT NULL THEN
    SELECT registry_id INTO linked_registry FROM oc_ontology.ontology_terms WHERE id=NEW.replacement_term_id;
    IF linked_registry IS DISTINCT FROM NEW.registry_id THEN RAISE EXCEPTION 'replacement term belongs to another registry'; END IF;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS ontology_term_links_valid ON oc_ontology.ontology_terms;
CREATE TRIGGER ontology_term_links_valid BEFORE INSERT OR UPDATE ON oc_ontology.ontology_terms FOR EACH ROW EXECUTE FUNCTION oc_ontology.enforce_term_links();

CREATE OR REPLACE FUNCTION oc_ontology.enforce_entity_resolution() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM oc_semantic.candidates WHERE id=NEW.candidate_id AND kind='ENTITY') THEN
    RAISE EXCEPTION 'ontology resolutions require entity candidates';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS ontology_entity_resolution_only ON oc_ontology.candidate_resolutions;
CREATE TRIGGER ontology_entity_resolution_only BEFORE INSERT OR UPDATE ON oc_ontology.candidate_resolutions FOR EACH ROW EXECUTE FUNCTION oc_ontology.enforce_entity_resolution();

CREATE OR REPLACE FUNCTION oc_ontology.enforce_evidence_hash_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.evidence_hash IS DISTINCT FROM OLD.evidence_hash OR NEW.evidence_object_id IS DISTINCT FROM OLD.evidence_object_id THEN
    RAISE EXCEPTION 'registered evidence identity is immutable';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS ontology_evidence_hash_immutable ON oc_ontology.evidence_registry;
CREATE TRIGGER ontology_evidence_hash_immutable BEFORE UPDATE ON oc_ontology.evidence_registry FOR EACH ROW EXECUTE FUNCTION oc_ontology.enforce_evidence_hash_immutable();
