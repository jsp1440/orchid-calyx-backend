-- BUILD-078 additive controlled publication gate.
-- Applies after 076a, 076b, and 077. This migration creates only metadata
-- and audit structures; it does not alter canonical graph or taxonomy tables.
CREATE SCHEMA IF NOT EXISTS oc_publication;

CREATE TABLE IF NOT EXISTS oc_publication.publication_runs (
  id BIGSERIAL PRIMARY KEY,
  mode TEXT NOT NULL CHECK (mode IN ('DRY_RUN','PUBLISH')),
  source_scope JSONB NOT NULL,
  manifest JSONB NOT NULL,
  manifest_digest CHAR(64) NOT NULL CHECK (manifest_digest ~ '^[0-9a-f]{64}$'),
  status TEXT NOT NULL DEFAULT 'PROPOSED' CHECK (status IN ('PROPOSED','DRY_RUN_COMPLETE','PUBLISHING','PUBLISHED','FAILED','BLOCKED','SUPERSEDED','ROLLED_BACK')),
  requesting_actor TEXT NOT NULL,
  approval_reference TEXT,
  publication_authority TEXT,
  reason TEXT NOT NULL,
  dry_run_run_id BIGINT REFERENCES oc_publication.publication_runs(id),
  item_count INTEGER NOT NULL DEFAULT 0 CHECK (item_count >= 0),
  ready_count INTEGER NOT NULL DEFAULT 0 CHECK (ready_count >= 0),
  blocked_count INTEGER NOT NULL DEFAULT 0 CHECK (blocked_count >= 0),
  inserted_node_count INTEGER NOT NULL DEFAULT 0 CHECK (inserted_node_count >= 0),
  linked_node_count INTEGER NOT NULL DEFAULT 0 CHECK (linked_node_count >= 0),
  inserted_edge_count INTEGER NOT NULL DEFAULT 0 CHECK (inserted_edge_count >= 0),
  linked_edge_count INTEGER NOT NULL DEFAULT 0 CHECK (linked_edge_count >= 0),
  canonical_graph_mutated BOOLEAN NOT NULL DEFAULT FALSE,
  before_graph_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
  after_graph_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
  error_summary TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  UNIQUE(mode, manifest_digest)
);

CREATE TABLE IF NOT EXISTS oc_publication.publication_items (
  id BIGSERIAL PRIMARY KEY,
  run_id BIGINT NOT NULL REFERENCES oc_publication.publication_runs(id) ON DELETE CASCADE,
  candidate_id BIGINT NOT NULL REFERENCES oc_semantic.candidates(id) ON DELETE CASCADE,
  item_type TEXT NOT NULL CHECK (item_type IN ('ENTITY','RELATIONSHIP')),
  state TEXT NOT NULL DEFAULT 'PROPOSED' CHECK (state IN ('PROPOSED','VALIDATING','READY','BLOCKED','DRY_RUN_COMPLETE','PUBLISHING','PUBLISHED','FAILED','SUPERSEDED','ROLLED_BACK')),
  action TEXT NOT NULL CHECK (action IN ('INSERT_NODE','LINK_EXISTING_NODE','INSERT_EDGE','LINK_EXISTING_EDGE','NO_OP','CONFLICT','BLOCKED')),
  canonical_key TEXT NOT NULL,
  graph_node_id BIGINT,
  graph_edge_id BIGINT,
  blockers JSONB NOT NULL DEFAULT '[]'::jsonb,
  conflict_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
  provenance JSONB NOT NULL,
  manifest_digest CHAR(64) NOT NULL CHECK (manifest_digest ~ '^[0-9a-f]{64}$'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(run_id, candidate_id)
);

CREATE TABLE IF NOT EXISTS oc_publication.publication_decisions (
  id BIGSERIAL PRIMARY KEY,
  run_id BIGINT NOT NULL REFERENCES oc_publication.publication_runs(id) ON DELETE CASCADE,
  item_id BIGINT REFERENCES oc_publication.publication_items(id) ON DELETE CASCADE,
  candidate_id BIGINT REFERENCES oc_semantic.candidates(id) ON DELETE CASCADE,
  decision TEXT NOT NULL CHECK (decision IN ('DRY_RUN','APPROVE','REJECT','PUBLISH','ROLLBACK','SUPERSEDE')),
  actor TEXT NOT NULL,
  reason TEXT NOT NULL,
  provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_publication.publication_conflicts (
  id BIGSERIAL PRIMARY KEY,
  run_id BIGINT NOT NULL REFERENCES oc_publication.publication_runs(id) ON DELETE CASCADE,
  item_id BIGINT REFERENCES oc_publication.publication_items(id) ON DELETE CASCADE,
  candidate_id BIGINT REFERENCES oc_semantic.candidates(id) ON DELETE CASCADE,
  conflict_type TEXT NOT NULL,
  details JSONB NOT NULL,
  resolved BOOLEAN NOT NULL DEFAULT FALSE,
  resolution JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS oc_publication.publication_audit_events (
  id BIGSERIAL PRIMARY KEY,
  run_id BIGINT REFERENCES oc_publication.publication_runs(id) ON DELETE CASCADE,
  item_id BIGINT REFERENCES oc_publication.publication_items(id) ON DELETE CASCADE,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT,
  previous_state JSONB,
  resulting_state JSONB,
  reason TEXT,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_publication.publication_rollbacks (
  id BIGSERIAL PRIMARY KEY,
  run_id BIGINT NOT NULL REFERENCES oc_publication.publication_runs(id),
  rollback_actor TEXT NOT NULL,
  reason TEXT NOT NULL,
  strategy TEXT NOT NULL CHECK (strategy IN ('SUPERSEDE_ONLY','MARK_ROLLED_BACK')),
  supersession_state JSONB NOT NULL DEFAULT '{}'::jsonb,
  canonical_graph_mutated BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS publication_runs_digest_idx ON oc_publication.publication_runs(manifest_digest, mode);
CREATE INDEX IF NOT EXISTS publication_runs_status_idx ON oc_publication.publication_runs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS publication_items_candidate_idx ON oc_publication.publication_items(candidate_id, state);
CREATE INDEX IF NOT EXISTS publication_items_canonical_key_idx ON oc_publication.publication_items(canonical_key);
CREATE INDEX IF NOT EXISTS publication_conflicts_open_idx ON oc_publication.publication_conflicts(run_id, candidate_id) WHERE NOT resolved;
CREATE INDEX IF NOT EXISTS publication_audit_target_idx ON oc_publication.publication_audit_events(target_type, target_id, occurred_at);

CREATE OR REPLACE FUNCTION oc_publication.enforce_item_state_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    RETURN NEW;
  END IF;
  IF OLD.state = NEW.state THEN
    RETURN NEW;
  END IF;
  IF OLD.state = 'PROPOSED' AND NEW.state IN ('VALIDATING','READY','BLOCKED','DRY_RUN_COMPLETE') THEN RETURN NEW; END IF;
  IF OLD.state = 'VALIDATING' AND NEW.state IN ('READY','BLOCKED','FAILED') THEN RETURN NEW; END IF;
  IF OLD.state = 'READY' AND NEW.state IN ('DRY_RUN_COMPLETE','PUBLISHING','BLOCKED','SUPERSEDED') THEN RETURN NEW; END IF;
  IF OLD.state = 'DRY_RUN_COMPLETE' AND NEW.state IN ('PUBLISHING','SUPERSEDED') THEN RETURN NEW; END IF;
  IF OLD.state = 'PUBLISHING' AND NEW.state IN ('PUBLISHED','FAILED') THEN RETURN NEW; END IF;
  IF OLD.state = 'PUBLISHED' AND NEW.state IN ('SUPERSEDED','ROLLED_BACK') THEN RETURN NEW; END IF;
  IF OLD.state IN ('FAILED','BLOCKED') AND NEW.state IN ('VALIDATING','SUPERSEDED') THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'invalid publication item state transition: % -> %', OLD.state, NEW.state;
END $$;

DROP TRIGGER IF EXISTS publication_item_state_transition_valid ON oc_publication.publication_items;
CREATE TRIGGER publication_item_state_transition_valid
BEFORE UPDATE ON oc_publication.publication_items
FOR EACH ROW EXECUTE FUNCTION oc_publication.enforce_item_state_transition();

CREATE OR REPLACE FUNCTION oc_publication.touch_publication_item_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS publication_item_touch_updated_at ON oc_publication.publication_items;
CREATE TRIGGER publication_item_touch_updated_at
BEFORE UPDATE ON oc_publication.publication_items
FOR EACH ROW EXECUTE FUNCTION oc_publication.touch_publication_item_updated_at();
