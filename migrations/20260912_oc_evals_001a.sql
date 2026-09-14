BEGIN;

CREATE SCHEMA IF NOT EXISTS oc_evals;

CREATE TABLE IF NOT EXISTS oc_evals.task_classes (
    fingerprint TEXT PRIMARY KEY,
    task_class_id TEXT NOT NULL,
    version TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(task_class_id, version)
);

CREATE TABLE IF NOT EXISTS oc_evals.strategies (
    fingerprint TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    version TEXT NOT NULL,
    task_class_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(strategy_id, version, fingerprint)
);

CREATE TABLE IF NOT EXISTS oc_evals.cases (
    fingerprint TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    version TEXT NOT NULL,
    task_class_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(case_id, version, fingerprint)
);

CREATE TABLE IF NOT EXISTS oc_evals.runs (
    identity_fingerprint TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_class_id TEXT NOT NULL,
    case_fingerprint TEXT NOT NULL,
    strategy_fingerprint TEXT NOT NULL,
    evaluator_set_fingerprint TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_evals.results (
    fingerprint TEXT PRIMARY KEY,
    run_identity_fingerprint TEXT NOT NULL,
    evaluator_id TEXT NOT NULL,
    evaluator_version TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_evals.decisions (
    decision_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    task_class_id TEXT NOT NULL,
    baseline_strategy_fingerprint TEXT NOT NULL,
    candidate_strategy_fingerprint TEXT NOT NULL,
    decision_state TEXT NOT NULL CHECK (decision_state IN (
        'PROMOTE','KEEP_BASELINE','LIMITED_CANARY','REJECT_QUALITY',
        'REJECT_SAFETY','REJECT_COST','REJECT_INSTABILITY','UNMEASURED','SUPERSEDED'
    )),
    rollback_strategy_fingerprint TEXT,
    supersedes_decision_id TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS oc_evals_runs_task_class_idx
    ON oc_evals.runs(task_class_id, created_at DESC);
CREATE INDEX IF NOT EXISTS oc_evals_decisions_task_class_idx
    ON oc_evals.decisions(task_class_id, created_at DESC);

COMMIT;
