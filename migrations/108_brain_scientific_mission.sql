-- Additive registration and lifecycle support for durable Brain missions.
INSERT INTO oc_missions.mission_types (
  mission_type, handler, input_schema, output_schema, required_authorization,
  risk_level, write_scope, allowed_database_schemas, forbidden_database_schemas,
  timeout_seconds, retry_policy, human_approval_required, dry_run_required,
  publication_authority_required, canonical_graph_writes_permitted,
  taxonomy_writes_prohibited, audit_requirements, active
) VALUES (
  'brain_scientific_mission', 'brain_scientific_mission', '{}'::jsonb, '{}'::jsonb,
  'owner_session', 'medium', 'scientific_artifacts_only',
  '["oc_missions","oc_candidate_knowledge","oc_scientific_interpretation","reasoning_ledger"]'::jsonb,
  '["oc_taxonomy"]'::jsonb, 300, '{"maximum_attempts":2}'::jsonb,
  TRUE, FALSE, FALSE, FALSE, TRUE,
  '["mission_event","scientific_artifact_ids"]'::jsonb, TRUE
)
ON CONFLICT (mission_type) DO UPDATE SET
  handler=EXCLUDED.handler,
  required_authorization=EXCLUDED.required_authorization,
  risk_level=EXCLUDED.risk_level,
  write_scope=EXCLUDED.write_scope,
  allowed_database_schemas=EXCLUDED.allowed_database_schemas,
  forbidden_database_schemas=EXCLUDED.forbidden_database_schemas,
  timeout_seconds=EXCLUDED.timeout_seconds,
  retry_policy=EXCLUDED.retry_policy,
  human_approval_required=EXCLUDED.human_approval_required,
  canonical_graph_writes_permitted=FALSE,
  taxonomy_writes_prohibited=TRUE,
  audit_requirements=EXCLUDED.audit_requirements,
  active=TRUE,
  updated_at=NOW();

CREATE OR REPLACE FUNCTION oc_missions.enforce_mission_state_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN RETURN NEW; END IF;
  IF OLD.state = NEW.state THEN RETURN NEW; END IF;
  IF OLD.state = 'draft' AND NEW.state IN ('awaiting_approval','cancelled','superseded') THEN RETURN NEW; END IF;
  IF OLD.state = 'awaiting_approval' AND NEW.state IN ('approved','blocked','cancelled') THEN RETURN NEW; END IF;
  IF OLD.state = 'approved' AND NEW.state IN ('queued','paused','cancelled','expired','superseded') THEN RETURN NEW; END IF;
  IF OLD.state = 'queued' AND NEW.state IN ('running','paused','completed','failed','cancelled','blocked','expired') THEN RETURN NEW; END IF;
  IF OLD.state = 'running' AND NEW.state IN ('queued','awaiting_approval','completed','failed','paused','cancelled','blocked') THEN RETURN NEW; END IF;
  IF OLD.state = 'paused' AND NEW.state IN ('approved','queued','cancelled','expired') THEN RETURN NEW; END IF;
  IF OLD.state = 'failed' AND NEW.state IN ('queued','cancelled','superseded','dead_lettered') THEN RETURN NEW; END IF;
  IF OLD.state IN ('completed','cancelled','expired','superseded','blocked') AND NEW.state IN ('superseded') THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'invalid mission state transition: % -> %', OLD.state, NEW.state;
END $$;
