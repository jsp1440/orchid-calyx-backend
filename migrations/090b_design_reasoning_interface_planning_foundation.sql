BEGIN;
CREATE SCHEMA IF NOT EXISTS design_planning;

CREATE OR REPLACE FUNCTION design_planning.reject_immutable_change() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'BUILD-090B immutable artifact cannot be changed'; END $$;

CREATE OR REPLACE FUNCTION design_planning.reject_future_state() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.lifecycle_state IN ('IMPLEMENTATION_AUTHORIZED','IMPLEMENTED','VALIDATED') THEN
    RAISE EXCEPTION 'BUILD-090B future implementation state is prohibited';
  END IF;
  RETURN NEW;
END $$;

CREATE TABLE IF NOT EXISTS design_planning.product_requests (
  artifact_id text PRIMARY KEY, logical_key text NOT NULL, version integer NOT NULL CHECK(version > 0),
  integrity_hash text NOT NULL UNIQUE, lifecycle_state text NOT NULL DEFAULT 'REQUEST_DRAFT',
  payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(logical_key, version)
);
CREATE TABLE IF NOT EXISTS design_planning.project_context_snapshots (
  artifact_id text PRIMARY KEY, logical_key text NOT NULL, version integer NOT NULL CHECK(version > 0),
  integrity_hash text NOT NULL UNIQUE, payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(logical_key, version)
);
CREATE TABLE IF NOT EXISTS design_planning.design_evidence_packages (
  artifact_id text PRIMARY KEY, logical_key text NOT NULL, version integer NOT NULL CHECK(version > 0),
  integrity_hash text NOT NULL UNIQUE, payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(logical_key, version)
);
CREATE TABLE IF NOT EXISTS design_planning.design_reasoning_records (
  artifact_id text PRIMARY KEY, logical_key text NOT NULL, version integer NOT NULL CHECK(version > 0),
  integrity_hash text NOT NULL UNIQUE, payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(logical_key, version)
);
CREATE TABLE IF NOT EXISTS design_planning.material_conflict_records (
  artifact_id text PRIMARY KEY, logical_key text NOT NULL, version integer NOT NULL CHECK(version > 0),
  integrity_hash text NOT NULL UNIQUE, payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(logical_key, version)
);
CREATE TABLE IF NOT EXISTS design_planning.interface_plans (
  artifact_id text PRIMARY KEY, logical_key text NOT NULL, version integer NOT NULL CHECK(version > 0),
  integrity_hash text NOT NULL UNIQUE, lifecycle_state text NOT NULL DEFAULT 'PLAN_DRAFTED',
  payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(logical_key, version),
  CHECK (lifecycle_state NOT IN ('IMPLEMENTATION_AUTHORIZED','IMPLEMENTED','VALIDATED'))
);
CREATE TABLE IF NOT EXISTS design_planning.review_records (
  review_id text PRIMARY KEY, artifact_id text NOT NULL, artifact_hash text NOT NULL,
  reviewer_role text NOT NULL, decision text NOT NULL, integrity_hash text NOT NULL UNIQUE,
  payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(artifact_hash, reviewer_role)
);
CREATE TABLE IF NOT EXISTS design_planning.audit_events (
  event_id text PRIMARY KEY, artifact_id text NOT NULL, integrity_hash text NOT NULL UNIQUE,
  payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_090b_evidence_payload ON design_planning.design_evidence_packages USING gin(payload);
CREATE INDEX IF NOT EXISTS idx_090b_plan_state ON design_planning.interface_plans(lifecycle_state, created_at);
CREATE INDEX IF NOT EXISTS idx_090b_review_artifact ON design_planning.review_records(artifact_id, created_at);
CREATE INDEX IF NOT EXISTS idx_090b_audit_artifact ON design_planning.audit_events(artifact_id, created_at);

DROP TRIGGER IF EXISTS future_state_090b ON design_planning.interface_plans;
CREATE TRIGGER future_state_090b BEFORE INSERT ON design_planning.interface_plans
FOR EACH ROW EXECUTE FUNCTION design_planning.reject_future_state();

DO $$ DECLARE tab text; BEGIN
  FOREACH tab IN ARRAY ARRAY['product_requests','project_context_snapshots','design_evidence_packages','design_reasoning_records','material_conflict_records','interface_plans','review_records','audit_events'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS immutable_090b ON design_planning.%I', tab);
    EXECUTE format('CREATE TRIGGER immutable_090b BEFORE UPDATE OR DELETE ON design_planning.%I FOR EACH ROW EXECUTE FUNCTION design_planning.reject_immutable_change()', tab);
  END LOOP;
END $$;
COMMIT;
