-- BUILD-083: additive orchestration state around the immutable BUILD-082 importer.
CREATE TABLE IF NOT EXISTS oc_import.bulk_runs (
  bulk_run_id BIGSERIAL PRIMARY KEY,
  source_id UUID NOT NULL REFERENCES oc_sources.sources(source_id),
  actor TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('PLANNED','RUNNING','INTERRUPTED','COMPLETED','COMPLETED_WITH_ERRORS','CANCELLED')),
  plan JSONB NOT NULL,
  started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ, cancelled_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS oc_import.bulk_items (
  bulk_run_id BIGINT NOT NULL REFERENCES oc_import.bulk_runs(bulk_run_id),
  registry_id BIGINT NOT NULL REFERENCES oc_sources.document_inventory(inventory_id),
  classification TEXT NOT NULL CHECK (classification IN ('NEW','UPDATED','UNCHANGED','DUPLICATE','UNSUPPORTED')),
  state TEXT NOT NULL CHECK (state IN ('PENDING','IMPORTED','UPDATED','SKIPPED','DUPLICATE','FAILED','CANCELLED')),
  error_code TEXT, result JSONB, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (bulk_run_id, registry_id)
);
CREATE INDEX IF NOT EXISTS bulk_runs_source_history_idx ON oc_import.bulk_runs(source_id, created_at DESC);
CREATE INDEX IF NOT EXISTS bulk_items_resume_idx ON oc_import.bulk_items(bulk_run_id, state, registry_id);
