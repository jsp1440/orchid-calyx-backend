# CALYX CORE — Reasoning schema production activation gate

## Status

Current-main replacement for stale PR #582. Production activation has **not** occurred.

## Live evidence that triggered this work

A read-only deployed preflight on 2026-08-07 passed health, owner authentication, database connectivity, required Knowledge Graph route mounting, persistent staging storage, and current-main deployment matching. A subsequent read-only request to `/api/reasoning-ledgers/eligible-for-publication` returned HTTP 503. The route converts SQLAlchemy failures into `LEDGER_PERSISTENCE_UNAVAILABLE`.

The eligibility query requires `reasoning_ledger.ledger_heads` and `reasoning_ledger.ledger_revisions`, created by additive migration `103_reasoning_ledger.sql`. The supervised publication adapter additionally requires `reasoning_publication.publication_artifacts` and `reasoning_publication.publication_attempts`, created by migration `105_reasoning_ledger_publication_adapter.sql`.

## Review defects corrected from PR #582

Two P1 review findings prevented stale PR #582 from being merge-ready even though its original CI was green.

1. **Table-name-only completion was insufficient.** A pre-existing partial table could cause `CREATE TABLE IF NOT EXISTS` to skip creation while `to_regclass` still reported success. The current-main replacement verifies all required columns, minimum constraint classes, named indexes, publication guard functions, and publication guard triggers. Missing `publication_artifacts.snapshot`, missing append-only/identity triggers, or missing required indexes/functions now makes the schema contract incomplete.
2. **Partial production mutation could be hidden after a later migration failure.** Migration 103 contains an explicit commit, and migration 105 executes under autocommit. The replacement records authorization separately from mutation attempt/outcome, records every migration as started/completed/failed, preserves `applied_migrations` and `failed_migration`, reconnects for fresh post-failure inspection, and reports `production_database_mutation_observed` plus `partial_application`. An execution error no longer rewrites an already-granted apply authorization to false or suppresses durable partial-mutation evidence.

## Activation contract

`scripts/activate_reasoning_publication_schemas.py` is read-only by default. It:

1. verifies exact reviewed Git blob identities for migrations 103 and 105;
2. verifies production prerequisites `research_station.projects` and `oc_knowledge_publication.publication_candidates`;
3. inspects target relation presence and the complete required schema contract before mutation;
4. writes a machine-readable evidence receipt;
5. never approves or publishes a Reasoning Ledger and never mutates the Knowledge Graph.

Production mutation requires all of the following simultaneously:

- manual `workflow_dispatch` of `CALYX Reasoning Schema Production Activation`;
- protected GitHub environment `production`;
- workflow input `apply_migrations=true`;
- exact current `main` checkout at execution time;
- `DATABASE_URL` production secret supplied only inside GitHub Actions;
- explicit confirmation token `APPLY_103_105` set only by the apply branch of the workflow;
- exact migration identity match;
- all prerequisite relations present.

The application order remains fixed: 103, then 105. After any apply attempt, the operator performs a **fresh database connection** for post-apply inspection and requires the full schema contract—not merely table names—to be complete.

After successful activation, the workflow performs only the existing **read-only** eligible-ledger discovery. It does not invoke `/{ledger_id}/publish`.

## Evidence semantics

The receipt distinguishes:

- `production_database_mutation_authorized`: the explicit gate was satisfied;
- `production_database_mutation_attempted`: execution actually began;
- `migration_results`: per-migration started/completed/error state;
- `applied_migrations`: migrations whose execution returned successfully;
- `failed_migration`: the migration where execution failed, when applicable;
- `production_database_mutation_observed`: successful migration completion or a before/after schema-contract change;
- `partial_application`: mutation was observed but the complete apply contract did not succeed;
- `activation_complete`: the full post-apply schema contract is present;
- `applied`: both migrations completed and the full post-apply contract passed with no blockers.

These fields prevent an interrupted or partially committed production migration from being represented as a clean no-mutation failure.

## Validation plan

The current-main release is validated on disposable PostgreSQL 16 with:

- Ruff and Python compilation;
- fail-closed unit coverage;
- a simulated 103-success/105-failure test proving completed work is retained in migration evidence;
- existing CALYX-BRAIN-003 migration dependency/reapplication tests;
- read-only preflight;
- 103→105 disposable apply;
- explicit assertions that the full schema contract, mutation evidence semantics, required `snapshot` column, guard functions, and guard triggers are complete;
- idempotent second apply;
- workflow governance audit;
- BUILD-088E publication-control regression.

Exact current-main run identifiers will be added before release.

## Governance boundary

Merging this implementation installs the protected gate only. It does **not** authorize production migration. Running the production workflow with `apply_migrations=true` changes the production database schema and therefore requires an explicit owner decision. Any later supervised publication of a reviewed ledger is a separate production Knowledge Graph governance decision.

No deployment, publication, taxonomy activation, production schema mutation, or Knowledge Graph mutation was performed while creating this gate.
