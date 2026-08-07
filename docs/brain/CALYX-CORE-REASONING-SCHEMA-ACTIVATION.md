# CALYX CORE — Reasoning schema production activation gate

## Status

Implementation prepared and validated for issue #580, parent epic #384. Production activation has **not** occurred.

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

PR #582 validation run `31225997703` passed on disposable PostgreSQL 16 after one lint-only corrective commit.

Passing evidence:

- Ruff and compile: passed;
- fail-closed activation tests: **4 passed**;
- existing CALYX-BRAIN-003 migration dependency/reapplication tests: **4 passed**;
- read-only preflight: passed with no blockers and `production_database_mutation_authorized=false`;
- migration identities matched the reviewed files:
  - 103 Git blob `b69fb53bf0771aa3730fb8a1b1c0d7a73a7a2153`, SHA-256 `00f56be05ee977e2d6a22eaad5cd2bddf9ae6c914f1650bdd7e531a4e322953e`;
  - 105 Git blob `d3a2fa44103a2f45f8b23a816b88496d0c88bf1e`, SHA-256 `c5ed3a2f40008018bf13e917ab4f0302dfcf0a5680a12fb7c74c79c1645cf178`;
- disposable 103→105 apply: passed, all five target tables present;
- second apply: passed with `activation_required=false`, proving idempotent replay;
- final disposable evidence artifact hash: `6fa759a9de7459839e4fd0943f418a1ef8d743f7a59b0b8b9103d10ea56534d3`;
- GitHub artifact ID `9012110913`, uploaded ZIP SHA-256 `5e0ef4a6b0be35b36ce54d61f71f488a6f678e9c4196cd0feafa19ab8bfac2da`;
- CALYX Workflow Governance Audit #71: passed;
- BUILD-088E #1021: passed.

The disposable preflight deliberately began with migration 103 already present and migration 105 absent because the existing CALYX-BRAIN-003 dependency test rolls back only the publication adapter. This exercised partial-state recovery: the gate correctly reported 103 present, 105 absent, then safely reapplied 103 and created 105 before verifying a no-op/idempotent second application.

## Governance boundary

Merging this implementation does not authorize production migration. Running the production workflow with `apply_migrations=true` changes the production database schema and therefore requires an explicit owner decision. The later supervised publication of any reviewed ledger is a separate production Knowledge Graph governance decision.

No deployment, publication, taxonomy activation, production schema mutation, or Knowledge Graph mutation was performed while creating or validating this gate.
