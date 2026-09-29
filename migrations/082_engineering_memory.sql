-- BUILD-1184: Continuum Engineering Memory v1.
-- Repository-scoped, non-scientific engineering memory for coding agents.
-- Forward migration.  Idempotent (CREATE ... IF NOT EXISTS), Postgres-flavored,
-- mirrors app/engineering_memory/models.py.  Rollback: 082_engineering_memory_downgrade.sql.
--
-- Governance: this material is engineering memory only.  It is
-- non_scientific_evidence, is never published to the Knowledge Graph, and must
-- not be applied to a production database without owner authorization.

CREATE TABLE IF NOT EXISTS engineering_memory_runs (
  run_id              VARCHAR(36)  PRIMARY KEY,
  executor            VARCHAR(80)  NOT NULL,
  provider            VARCHAR(120),
  workspace_scope     VARCHAR(240) NOT NULL,
  repository          VARCHAR(240) NOT NULL,
  branch              VARCHAR(240),
  task_ref            VARCHAR(240),
  issue_ref           VARCHAR(120),
  pr_ref              VARCHAR(120),
  commit_shas         JSONB        NOT NULL DEFAULT '[]'::jsonb,
  outcome             VARCHAR(20)  NOT NULL,
  checks              JSONB        NOT NULL DEFAULT '{}'::jsonb,
  sanitized_summary   TEXT         NOT NULL DEFAULT '',
  tokens_input        INTEGER,
  tokens_output       INTEGER,
  turns               INTEGER,
  elapsed_ms          INTEGER,
  data_classification VARCHAR(40)  NOT NULL,
  evidence_class      VARCHAR(40)  NOT NULL DEFAULT 'non_scientific_evidence',
  redaction_status    VARCHAR(20)  NOT NULL,
  redaction_report    JSONB        NOT NULL DEFAULT '{}'::jsonb,
  created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  CONSTRAINT engineering_memory_runs_evidence_class_non_scientific
    CHECK (evidence_class = 'non_scientific_evidence'),
  CONSTRAINT engineering_memory_runs_redaction_status_valid
    CHECK (redaction_status IN ('clean','redacted')),
  CONSTRAINT engineering_memory_runs_outcome_valid
    CHECK (outcome IN ('success','failure','partial'))
);
CREATE INDEX IF NOT EXISTS idx_eng_mem_runs_scope ON engineering_memory_runs(workspace_scope);
CREATE INDEX IF NOT EXISTS idx_eng_mem_runs_scope_repo ON engineering_memory_runs(workspace_scope, repository);

CREATE TABLE IF NOT EXISTS engineering_memory_lessons (
  lesson_id              VARCHAR(36)  PRIMARY KEY,
  workspace_scope        VARCHAR(240) NOT NULL,
  repository             VARCHAR(240) NOT NULL,
  module                 VARCHAR(240),
  problem                TEXT         NOT NULL,
  cause                  TEXT         NOT NULL DEFAULT '',
  solution               TEXT         NOT NULL,
  applicability          TEXT         NOT NULL DEFAULT '',
  tags                   JSONB        NOT NULL DEFAULT '[]'::jsonb,
  lexical_document       TEXT         NOT NULL DEFAULT '',
  embedding              JSONB,
  source_run_id          VARCHAR(36)  REFERENCES engineering_memory_runs(run_id),
  github_provenance      JSONB        NOT NULL DEFAULT '{}'::jsonb,
  status                 VARCHAR(20)  NOT NULL DEFAULT 'candidate',
  verification_status    VARCHAR(20)  NOT NULL DEFAULT 'unverified',
  verification_evidence  JSONB        NOT NULL DEFAULT '{}'::jsonb,
  confidence             VARCHAR(20)  NOT NULL DEFAULT 'low',
  invalidated_reason     VARCHAR(240),
  dependency_fingerprint VARCHAR(64),
  schema_fingerprint     VARCHAR(64),
  file_fingerprints      JSONB        NOT NULL DEFAULT '{}'::jsonb,
  data_classification    VARCHAR(40)  NOT NULL,
  evidence_class         VARCHAR(40)  NOT NULL DEFAULT 'non_scientific_evidence',
  redaction_status       VARCHAR(20)  NOT NULL,
  redaction_report       JSONB        NOT NULL DEFAULT '{}'::jsonb,
  expires_at             TIMESTAMPTZ,
  created_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  CONSTRAINT engineering_memory_lessons_evidence_class_non_scientific
    CHECK (evidence_class = 'non_scientific_evidence'),
  CONSTRAINT engineering_memory_lessons_status_valid
    CHECK (status IN ('candidate','verified','invalidated','expired')),
  CONSTRAINT engineering_memory_lessons_verification_valid
    CHECK (verification_status IN ('unverified','verified','refuted')),
  CONSTRAINT engineering_memory_lessons_redaction_status_valid
    CHECK (redaction_status IN ('clean','redacted'))
);
CREATE INDEX IF NOT EXISTS idx_eng_mem_lessons_scope_status ON engineering_memory_lessons(workspace_scope, status);
CREATE INDEX IF NOT EXISTS idx_eng_mem_lessons_scope_module ON engineering_memory_lessons(workspace_scope, module);
-- Optional Postgres full-text acceleration for the lexical representation.
-- The service also computes a portable BM25 ranking in-process, so this index
-- is an optimization, not a correctness requirement.
CREATE INDEX IF NOT EXISTS idx_eng_mem_lessons_lexical_fts
  ON engineering_memory_lessons USING GIN (to_tsvector('english', lexical_document));

CREATE TABLE IF NOT EXISTS engineering_memory_retrievals (
  retrieval_id          VARCHAR(36)  PRIMARY KEY,
  workspace_scope       VARCHAR(240) NOT NULL,
  repository            VARCHAR(240) NOT NULL,
  module                VARCHAR(240),
  query_text            TEXT         NOT NULL,
  retrieved             JSONB        NOT NULL DEFAULT '[]'::jsonb,
  injected              BOOLEAN      NOT NULL DEFAULT FALSE,
  injected_char_budget  INTEGER,
  injected_chars        INTEGER,
  feedback              VARCHAR(20),
  feedback_outcome      JSONB,
  latency_ms            INTEGER,
  estimated_tokens_saved INTEGER,
  created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_eng_mem_retrievals_scope ON engineering_memory_retrievals(workspace_scope);
