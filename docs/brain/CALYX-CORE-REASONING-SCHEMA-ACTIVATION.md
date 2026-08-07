# CALYX CORE — Reasoning schema production activation gate

## Status

Implementation prepared for issue #580, parent epic #384. Production activation has **not** occurred.

## Live evidence that triggered this work

A read-only deployed preflight on 2026-08-07 passed health, owner authentication, database connectivity, required Knowledge Graph route mounting, persistent staging storage, and current-main deployment matching. A subsequent read-only request to `/api/reasoning-ledgers/eligible-for-publication` returned HTTP 503. The route converts SQLAlchemy failures into `LEDGER_PERSISTENCE_UNAVAILABLE`.

The eligibility query requires:

- `reasoning_ledger.ledger_heads`
- `reasoning_ledger.ledger_revisions`

Those are created by additive migration `103_reasoning_ledger.sql`. The supervised publication adapter additionally requires `reasoning_publication.publication_artifacts` and `reasoning_publication.publication_attempts`, created by migration `105_reasoning_ledger_publication_adapter.sql`.

## Activation contract

`scripts/activate_reasoning_publication_schemas.py` is read-only by default. It:

1. verifies exact reviewed Git blob identities for migrations 103 and 105;
2. verifies production prerequisites `research_station.projects` and `oc_knowledge_publication.publication_candidates`;
3. reports target-table presence before any mutation;
4. writes a machine-readable evidence receipt;
5. never approves or publishes a Reasoning Ledger and never mutates the Knowledge Graph.

Production mutation requires all of the following simultaneously:

- manual `workflow_dispatch` of `CALYX Reasoning Schema Production Activation`;
- protected GitHub environment `production`;
- workflow input `apply_migrations=true`;
- exact current `main` checkout at execution time;
- `DATABASE_URL` production secret supplied only inside GitHub Actions;
- explicit confirmation token `APPLY_103_105` set by the apply branch of the workflow;
- exact migration identity match;
- all prerequisite relations present.

The application order is fixed: 103, then 105. Both migrations are additive/idempotent. Post-apply verification requires all five target tables to resolve through `to_regclass`.

After successful activation, the workflow performs only one additional action: the existing **read-only** eligible-ledger discovery. It does not invoke `/{ledger_id}/publish`.

## Validation

The PR validation workflow uses disposable PostgreSQL 16. It runs:

- Ruff and compile checks for the activation script;
- fail-closed unit tests;
- the existing CALYX-BRAIN-003 migration dependency/reapplication test;
- read-only activation preflight;
- 103→105 application on the disposable database;
- a second application proving idempotent replay;
- machine-readable receipt upload.

## Governance boundary

Merging this implementation does not authorize production migration. Running the production workflow with `apply_migrations=true` changes the production database schema and therefore requires an explicit owner decision. The later supervised publication of any reviewed ledger is a separate production Knowledge Graph governance decision.

No deployment, publication, taxonomy activation, production schema mutation, or Knowledge Graph mutation was performed while creating this gate.
