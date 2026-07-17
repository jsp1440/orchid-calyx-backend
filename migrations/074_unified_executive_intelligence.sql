BEGIN;
CREATE SCHEMA IF NOT EXISTS oc_ai;

CREATE TABLE IF NOT EXISTS oc_ai.providers (
  id BIGSERIAL PRIMARY KEY,
  provider_key TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  capabilities TEXT[] NOT NULL DEFAULT '{}',
  priority INTEGER NOT NULL DEFAULT 100,
  cost_rank INTEGER NOT NULL DEFAULT 100,
  managed BOOLEAN NOT NULL DEFAULT TRUE,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  healthy BOOLEAN NOT NULL DEFAULT TRUE,
  configuration JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_ai.budget_policies (
  id BIGSERIAL PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  project_id TEXT,
  provider_key TEXT,
  soft_limit_usd NUMERIC(14,6),
  hard_limit_usd NUMERIC(14,6),
  policy_mode TEXT NOT NULL DEFAULT 'WARN' CHECK (policy_mode IN ('WARN','DOWNGRADE','BLOCK')),
  period TEXT NOT NULL DEFAULT 'MONTHLY' CHECK (period IN ('DAILY','MONTHLY','LIFETIME')),
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ai_budget_policy_scope_uq
ON oc_ai.budget_policies(workspace_id, COALESCE(project_id,''), COALESCE(provider_key,''), period);

CREATE TABLE IF NOT EXISTS oc_ai.recommendations (
  id BIGSERIAL PRIMARY KEY,
  source_id BIGINT NOT NULL REFERENCES oc_intake.sources(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL DEFAULT 'default',
  project_id TEXT,
  recommendation_type TEXT NOT NULL,
  title TEXT NOT NULL,
  rationale TEXT NOT NULL,
  priority TEXT NOT NULL CHECK (priority IN ('LOW','MEDIUM','HIGH','CRITICAL')),
  confidence NUMERIC(5,4) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  expected_benefit TEXT,
  estimated_effort_minutes INTEGER,
  estimated_ai_cost_usd NUMERIC(14,6) NOT NULL DEFAULT 0,
  proposed_action_type TEXT,
  proposed_destination TEXT,
  required_capability TEXT,
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','APPROVED','REJECTED','ROUTED')),
  decision_actor TEXT,
  decision_notes TEXT,
  decided_at TIMESTAMPTZ,
  workflow_action_id BIGINT REFERENCES oc_workflow.actions(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ai_recommendation_dedup_uq
ON oc_ai.recommendations(source_id, workspace_id, COALESCE(project_id,''), recommendation_type);

CREATE TABLE IF NOT EXISTS oc_ai.usage_ledger (
  id BIGSERIAL PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  project_id TEXT,
  provider_key TEXT NOT NULL,
  model_key TEXT NOT NULL,
  task_type TEXT NOT NULL,
  recommendation_id BIGINT REFERENCES oc_ai.recommendations(id) ON DELETE SET NULL,
  workflow_action_id BIGINT REFERENCES oc_workflow.actions(id) ON DELETE SET NULL,
  input_units BIGINT,
  output_units BIGINT,
  estimated_cost_usd NUMERIC(14,6) NOT NULL DEFAULT 0,
  actual_cost_usd NUMERIC(14,6),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ai_recommendations_queue_idx ON oc_ai.recommendations(status, priority, created_at DESC);
CREATE INDEX IF NOT EXISTS ai_usage_scope_idx ON oc_ai.usage_ledger(workspace_id, project_id, occurred_at DESC);
COMMIT;
