-- CALYX-BRAIN-003 additive governed publication adapter.
CREATE SCHEMA IF NOT EXISTS reasoning_publication;

CREATE TABLE IF NOT EXISTS reasoning_publication.publication_artifacts (
    publication_artifact_id uuid PRIMARY KEY,
    artifact_hash char(64) NOT NULL UNIQUE,
    ledger_id uuid NOT NULL REFERENCES reasoning_ledger.ledger_heads(ledger_id) ON DELETE RESTRICT,
    ledger_version integer NOT NULL CHECK (ledger_version > 0),
    review_content_hash char(64) NOT NULL,
    owner_subject text NOT NULL,
    project_id uuid NOT NULL REFERENCES research_station.projects(project_id) ON DELETE RESTRICT,
    status text NOT NULL CHECK (status IN ('prepared','validated','submitted','published','rejected','blocked','superseded','retracted')),
    snapshot jsonb NOT NULL,
    canonical_publication_id bigint REFERENCES oc_knowledge_publication.publication_candidates(publication_id) ON DELETE RESTRICT,
    canonical_graph_result jsonb,
    failure_reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (ledger_id, ledger_version, review_content_hash, artifact_hash)
);

CREATE TABLE IF NOT EXISTS reasoning_publication.publication_attempts (
    attempt_id bigserial PRIMARY KEY,
    publication_artifact_id uuid NOT NULL REFERENCES reasoning_publication.publication_artifacts(publication_artifact_id) ON DELETE RESTRICT,
    attempt_number integer NOT NULL CHECK (attempt_number > 0),
    outcome text NOT NULL,
    actor text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (publication_artifact_id, attempt_number)
);

CREATE INDEX IF NOT EXISTS idx_reasoning_publication_scope
    ON reasoning_publication.publication_artifacts(owner_subject, project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_reasoning_publication_ledger
    ON reasoning_publication.publication_artifacts(ledger_id, ledger_version);
CREATE INDEX IF NOT EXISTS idx_reasoning_publication_attempt
    ON reasoning_publication.publication_attempts(publication_artifact_id, attempt_number);

CREATE OR REPLACE FUNCTION reasoning_publication.protect_published_artifact()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status IN ('published','superseded','retracted') THEN
        RAISE EXCEPTION 'PUBLISHED_REASONING_ARTIFACT_IS_IMMUTABLE';
    END IF;
    IF NEW.publication_artifact_id <> OLD.publication_artifact_id
       OR NEW.artifact_hash <> OLD.artifact_hash
       OR NEW.ledger_id <> OLD.ledger_id
       OR NEW.ledger_version <> OLD.ledger_version
       OR NEW.review_content_hash <> OLD.review_content_hash
       OR NEW.owner_subject <> OLD.owner_subject
       OR NEW.project_id <> OLD.project_id
       OR NEW.snapshot <> OLD.snapshot THEN
        RAISE EXCEPTION 'REASONING_PUBLICATION_IDENTITY_IS_IMMUTABLE';
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS protect_reasoning_publication_identity
    ON reasoning_publication.publication_artifacts;
CREATE TRIGGER protect_reasoning_publication_identity
BEFORE UPDATE ON reasoning_publication.publication_artifacts
FOR EACH ROW EXECUTE FUNCTION reasoning_publication.protect_published_artifact();

CREATE OR REPLACE FUNCTION reasoning_publication.reject_attempt_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'REASONING_PUBLICATION_ATTEMPTS_ARE_APPEND_ONLY';
END $$;
DROP TRIGGER IF EXISTS protect_reasoning_publication_attempt
    ON reasoning_publication.publication_attempts;
CREATE TRIGGER protect_reasoning_publication_attempt
BEFORE UPDATE OR DELETE ON reasoning_publication.publication_attempts
FOR EACH ROW EXECUTE FUNCTION reasoning_publication.reject_attempt_mutation();

REVOKE UPDATE, DELETE ON reasoning_publication.publication_attempts FROM PUBLIC;
