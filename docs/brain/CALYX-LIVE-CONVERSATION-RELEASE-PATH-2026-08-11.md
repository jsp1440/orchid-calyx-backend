# CALYX Live Conversation — Release Path Checkpoint

Status: **TECHNICAL RELEASE PATH VALIDATED / PRODUCTION ACTIVATION AND DEPLOYMENT NOT AUTHORIZED**

## Canonical conversation capability

CALYX-CONV v3 is merged into backend `main` through PR #798. The cumulative Research Station Ask CALYX stack through RS-15 is merged into Research Station `main` through PR #17.

## Browser/client acceptance gate

Research Station PR #19 adds `CALYX LIVE CONVERSATION — E2E-001`.

Validated implementation/documentation head: `004ae583485b5248da83d3da91f2e8365c16457c`.
CI run: `31525561184`.
Job: `93892890344`.

Result: **PASS** — formatting, lint, full Vitest suite including E2E-001, and production build.

The client contract proves create → ask → reopen → exact-document follow-up → exact persisted source/revision link → Markdown report export with owner-session authentication and permanent non-evidence/non-publication/non-KG-mutation boundaries.

This is mocked transport and is **not** production verification.

## Atomic Research Station schema activation

Backend PR #819 validates the existing guarded activation CLI with the explicit `research-station-conversations` profile.

Exact validated release-tooling head before this Brain-only checkpoint: `7a1a22affde15b9c675da09039d6828bbefdd812`.

Required workflows:

- CALYX Reasoning Prerequisite Activation Validation — run `31526857397` — **PASS**.
- CALYX Workflow Governance Audit — run `31526857126` — **PASS**.
- BUILD-088E Validation — run `31526857149` — **PASS**.

Disposable PostgreSQL matrix:

- PostgreSQL 15 — **PASS**.
- PostgreSQL 16 — **PASS**.
- PostgreSQL 17 / 17.10 — **PASS**.
- historical/default reasoning-prerequisite profile — **PASS**.

Focused Research Station atomic tests: **9/9 PASS** on PG17, including the explicit `COMPLETE_101_ONLY` → apply migration 140 only → `COMPLETE_101_140` safe-resume regression.

Validated behavior includes:

- exact migration-101 and migration-140 blob identities;
- transaction-scoped advisory serialization using lock `82078079`;
- one transaction through 101/140 postconditions;
- full rollback after intentional failure following 101 or 140;
- canonical rerun no-op;
- malformed/partial state refusal;
- canonical migration-101-only resume by applying only 140;
- FK, authority checks, append-only triggers, index/constraint/default/nullability checks, and PUBLIC privilege checks.

## Truthful activation receipts

The validated disposable PG17 receipt records:

- `target_environment=disposable`;
- PostgreSQL `17.10`, server version number `170010`;
- generic `database_mutation_authorized=true` and `database_mutation_attempted=true` for the disposable apply;
- `production_database_mutation_authorized=false`;
- `production_database_mutation_attempted=false`;
- `publication_authorized=false`;
- `knowledge_graph_mutation_authorized=false`.

Disposable evidence must never be described as production mutation or authorization.

## Guarded production-workflow wiring

The existing manual production activation workflow is extended in PR #819 rather than creating a parallel migration framework.

Validated characteristics:

- `workflow_dispatch` only;
- job refuses non-`main` dispatch (`github.ref == refs/heads/main`);
- production environment remains protected;
- exact current-main checkout is reverified;
- default action remains read-only preflight (`apply_prerequisites=false`);
- operator explicitly selects `reasoning-prerequisites` or `research-station-conversations`;
- Research Station preflight declares `CALYX_ACTIVATION_TARGET_ENVIRONMENT=production` but has no mutation confirmation;
- Research Station apply requires the distinct `APPLY_RESEARCH_STATION_101_140` confirmation token;
- receipts are uploaded regardless of outcome.

**The production workflow was not dispatched during this work.**

## Production facts already verified read-only

Previous read-only Neon preflight observed PostgreSQL 17.10 and `pgcrypto` 1.3, but no `research_station` schema and therefore no migration-101 prerequisite or migration-140 target tables.

No production schema or row mutation occurred.

## Remaining release dependencies

1. PR #819 governed review/merge disposition; do not merge without authorization.
2. Identify and verify the intended production CALYX-CONV application database role and required privileges.
3. A separate governance authorization for production Research Station schema activation (migration 101 plus migration 140 through the validated atomic profile).
4. Post-schema read-only verification.
5. A separate governance authorization for Research Station/CALYX-CONV deployment and persistent-conversation traffic.
6. Configure deployed Research Station URLs and add its exact origin through the existing `CORS_ALLOW_ORIGIN` configuration.
7. Run live browser E2E-001 after deployment; only then mark Talk-to-Calyx **PRODUCTION VERIFIED**.

## Governance

NOT AUTHORIZED / NOT PERFORMED:

- production migration 101 or 140;
- production deployment;
- persistent-conversation production traffic;
- Candidate Knowledge promotion;
- scientific publication;
- taxonomy activation;
- production Knowledge Graph mutation.
