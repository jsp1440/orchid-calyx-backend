-- BUILD-079 additive controlled mission queue and autonomous orchestration.
-- Creates oc_missions only. Does not alter taxonomy, ontology, publication, or graph schemas.
CREATE SCHEMA IF NOT EXISTS oc_missions;

CREATE TABLE IF NOT EXISTS oc_missions.mission_types (
  mission_type TEXT PRIMARY KEY,
  handler TEXT NOT NULL,
  input_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
  output_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
  required_authorization TEXT NOT NULL,
  risk_level TEXT NOT NULL CHECK (risk_level IN ('low','medium','high','critical')),
  write_scope TEXT NOT NULL,
  allowed_database_schemas JSONB NOT NULL DEFAULT '[]'::jsonb,
  forbidden_database_schemas JSONB NOT NULL DEFAULT '["oc_taxonomy"]'::jsonb,
  timeout_seconds INTEGER NOT NULL CHECK (timeout_seconds BETWEEN 1 AND 3600),
  retry_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  human_approval_required BOOLEAN NOT NULL DEFAULT FALSE,
  dry_run_required BOOLEAN NOT NULL DEFAULT FALSE,
  publication_authority_required BOOLEAN NOT NULL DEFAULT FALSE,
  canonical_graph_writes_permitted BOOLEAN NOT NULL DEFAULT FALSE,
  taxonomy_writes_prohibited BOOLEAN NOT NULL DEFAULT TRUE,
  audit_requirements JSONB NOT NULL DEFAULT '[]'::jsonb,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_missions.mission_templates (
  id BIGSERIAL PRIMARY KEY,
  template_key TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  mission_type TEXT NOT NULL REFERENCES oc_missions.mission_types(mission_type),
  default_priority INTEGER NOT NULL DEFAULT 50 CHECK (default_priority BETWEEN 0 AND 100),
  default_risk TEXT NOT NULL CHECK (default_risk IN ('low','medium','high','critical')),
  input_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
  default_inputs JSONB NOT NULL DEFAULT '{}'::jsonb,
  required_approvals JSONB NOT NULL DEFAULT '[]'::jsonb,
  allowed_actions JSONB NOT NULL DEFAULT '[]'::jsonb,
  prohibited_actions JSONB NOT NULL DEFAULT '[]'::jsonb,
  scheduling_defaults JSONB NOT NULL DEFAULT '{}'::jsonb,
  retry_defaults JSONB NOT NULL DEFAULT '{}'::jsonb,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
  supersedes_template_id BIGINT REFERENCES oc_missions.mission_templates(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(template_key, version)
);

CREATE TABLE IF NOT EXISTS oc_missions.missions (
  mission_id BIGSERIAL PRIMARY KEY,
  mission_key TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  mission_type TEXT NOT NULL REFERENCES oc_missions.mission_types(mission_type),
  requested_by TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 50 CHECK (priority BETWEEN 0 AND 100),
  state TEXT NOT NULL DEFAULT 'draft' CHECK (state IN ('draft','awaiting_approval','approved','queued','running','paused','completed','failed','cancelled','expired','superseded','blocked')),
  risk_level TEXT NOT NULL CHECK (risk_level IN ('low','medium','high','critical')),
  authorization_level TEXT NOT NULL,
  schedule_type TEXT NOT NULL DEFAULT 'manual' CHECK (schedule_type IN ('manual','scheduled','recurring')),
  scheduled_at TIMESTAMPTZ,
  recurrence_rule TEXT,
  next_run_at TIMESTAMPTZ,
  maximum_runs INTEGER CHECK (maximum_runs IS NULL OR maximum_runs > 0),
  completed_runs INTEGER NOT NULL DEFAULT 0 CHECK (completed_runs >= 0),
  failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
  maximum_failures INTEGER NOT NULL DEFAULT 3 CHECK (maximum_failures >= 0),
  retry_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  timeout_seconds INTEGER NOT NULL DEFAULT 60 CHECK (timeout_seconds BETWEEN 1 AND 3600),
  input_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
  output_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
  execution_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  allowed_actions JSONB NOT NULL DEFAULT '[]'::jsonb,
  prohibited_actions JSONB NOT NULL DEFAULT '[]'::jsonb,
  target_services JSONB NOT NULL DEFAULT '[]'::jsonb,
  target_domains JSONB NOT NULL DEFAULT '[]'::jsonb,
  owner_approval_reference TEXT,
  approval_timestamp TIMESTAMPTZ,
  paused_at TIMESTAMPTZ,
  cancelled_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  last_error TEXT,
  version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
  supersedes_mission_id BIGINT REFERENCES oc_missions.missions(mission_id),
  created_from_template_id BIGINT REFERENCES oc_missions.mission_templates(id),
  idempotency_key TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (state <> 'approved' OR owner_approval_reference IS NOT NULL),
  CHECK (state <> 'approved' OR approval_timestamp IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS oc_missions.mission_dependencies (
  mission_id BIGINT NOT NULL REFERENCES oc_missions.missions(mission_id) ON DELETE CASCADE,
  depends_on_mission_id BIGINT NOT NULL REFERENCES oc_missions.missions(mission_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (mission_id, depends_on_mission_id),
  CHECK (mission_id <> depends_on_mission_id)
);

CREATE TABLE IF NOT EXISTS oc_missions.mission_jobs (
  job_id BIGSERIAL PRIMARY KEY,
  mission_id BIGINT NOT NULL REFERENCES oc_missions.missions(mission_id) ON DELETE CASCADE,
  job_type TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','available','claimed','running','succeeded','retry_wait','failed','cancelled','dead_lettered','blocked','skipped')),
  sequence INTEGER NOT NULL DEFAULT 1 CHECK (sequence > 0),
  priority INTEGER NOT NULL DEFAULT 50 CHECK (priority BETWEEN 0 AND 100),
  scheduled_at TIMESTAMPTZ,
  available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  claimed_at TIMESTAMPTZ,
  lease_expires_at TIMESTAMPTZ,
  worker_id TEXT,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  attempt_number INTEGER NOT NULL DEFAULT 0 CHECK (attempt_number >= 0),
  maximum_attempts INTEGER NOT NULL DEFAULT 3 CHECK (maximum_attempts > 0),
  input_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  output_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  error_code TEXT,
  error_message TEXT,
  traceback_digest CHAR(64),
  idempotency_key TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_missions.mission_events (
  event_id BIGSERIAL PRIMARY KEY,
  actor TEXT NOT NULL,
  actor_type TEXT NOT NULL,
  event_type TEXT NOT NULL,
  mission_id BIGINT REFERENCES oc_missions.missions(mission_id) ON DELETE CASCADE,
  job_id BIGINT REFERENCES oc_missions.mission_jobs(job_id) ON DELETE CASCADE,
  previous_state TEXT,
  new_state TEXT,
  request_correlation_id TEXT,
  approval_reference TEXT,
  input_digest CHAR(64),
  output_digest CHAR(64),
  error_digest CHAR(64),
  worker_id TEXT,
  service_version TEXT NOT NULL DEFAULT 'BUILD-079',
  commit_sha TEXT,
  event_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_missions.job_attempts (
  attempt_id BIGSERIAL PRIMARY KEY,
  job_id BIGINT NOT NULL REFERENCES oc_missions.mission_jobs(job_id) ON DELETE CASCADE,
  attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
  worker_id TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  state TEXT NOT NULL CHECK (state IN ('running','succeeded','failed','dead_lettered')),
  output_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  error_code TEXT,
  error_message TEXT,
  traceback_digest CHAR(64),
  UNIQUE(job_id, attempt_number)
);

CREATE TABLE IF NOT EXISTS oc_missions.runtime_workers (
  worker_id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('starting','alive','stopping','stopped','failed')),
  heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  lease_recovery_count INTEGER NOT NULL DEFAULT 0 CHECK (lease_recovery_count >= 0),
  runtime_blocker TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_missions.dead_letter_jobs (
  id BIGSERIAL PRIMARY KEY,
  job_id BIGINT NOT NULL UNIQUE REFERENCES oc_missions.mission_jobs(job_id),
  mission_id BIGINT NOT NULL REFERENCES oc_missions.missions(mission_id),
  final_error_code TEXT,
  final_error_message TEXT,
  dead_lettered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS missions_state_priority_idx ON oc_missions.missions(state, priority DESC, next_run_at NULLS FIRST);
CREATE INDEX IF NOT EXISTS missions_type_state_idx ON oc_missions.missions(mission_type, state);
CREATE INDEX IF NOT EXISTS mission_jobs_claim_idx ON oc_missions.mission_jobs(state, available_at, priority DESC, job_id);
CREATE INDEX IF NOT EXISTS mission_jobs_lease_idx ON oc_missions.mission_jobs(state, lease_expires_at) WHERE state IN ('claimed','running');
CREATE INDEX IF NOT EXISTS mission_events_mission_idx ON oc_missions.mission_events(mission_id, occurred_at, event_id);
CREATE INDEX IF NOT EXISTS mission_events_job_idx ON oc_missions.mission_events(job_id, occurred_at, event_id);
CREATE INDEX IF NOT EXISTS dead_letter_mission_idx ON oc_missions.dead_letter_jobs(mission_id, dead_lettered_at DESC);

CREATE OR REPLACE FUNCTION oc_missions.reject_event_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'mission audit events are append-only';
END $$;
DROP TRIGGER IF EXISTS mission_events_append_only ON oc_missions.mission_events;
CREATE TRIGGER mission_events_append_only BEFORE UPDATE OR DELETE ON oc_missions.mission_events
FOR EACH ROW EXECUTE FUNCTION oc_missions.reject_event_mutation();

CREATE OR REPLACE FUNCTION oc_missions.enforce_mission_state_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN RETURN NEW; END IF;
  IF OLD.state = NEW.state THEN RETURN NEW; END IF;
  IF OLD.state = 'draft' AND NEW.state IN ('awaiting_approval','cancelled','superseded') THEN RETURN NEW; END IF;
  IF OLD.state = 'awaiting_approval' AND NEW.state IN ('approved','blocked','cancelled') THEN RETURN NEW; END IF;
  IF OLD.state = 'approved' AND NEW.state IN ('queued','paused','cancelled','expired','superseded') THEN RETURN NEW; END IF;
  IF OLD.state = 'queued' AND NEW.state IN ('running','paused','completed','failed','cancelled','blocked','expired') THEN RETURN NEW; END IF;
  IF OLD.state = 'running' AND NEW.state IN ('queued','completed','failed','paused','cancelled','blocked') THEN RETURN NEW; END IF;
  IF OLD.state = 'paused' AND NEW.state IN ('approved','queued','cancelled','expired') THEN RETURN NEW; END IF;
  IF OLD.state = 'failed' AND NEW.state IN ('queued','cancelled','superseded','dead_lettered') THEN RETURN NEW; END IF;
  IF OLD.state IN ('completed','cancelled','expired','superseded','blocked') AND NEW.state IN ('superseded') THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'invalid mission state transition: % -> %', OLD.state, NEW.state;
END $$;
DROP TRIGGER IF EXISTS missions_state_transition_valid ON oc_missions.missions;
CREATE TRIGGER missions_state_transition_valid BEFORE UPDATE ON oc_missions.missions
FOR EACH ROW EXECUTE FUNCTION oc_missions.enforce_mission_state_transition();

CREATE OR REPLACE FUNCTION oc_missions.touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS missions_touch_updated_at ON oc_missions.missions;
CREATE TRIGGER missions_touch_updated_at BEFORE UPDATE ON oc_missions.missions
FOR EACH ROW EXECUTE FUNCTION oc_missions.touch_updated_at();
DROP TRIGGER IF EXISTS mission_jobs_touch_updated_at ON oc_missions.mission_jobs;
CREATE TRIGGER mission_jobs_touch_updated_at BEFORE UPDATE ON oc_missions.mission_jobs
FOR EACH ROW EXECUTE FUNCTION oc_missions.touch_updated_at();
