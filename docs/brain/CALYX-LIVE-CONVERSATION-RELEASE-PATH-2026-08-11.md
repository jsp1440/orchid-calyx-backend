# CALYX Live Conversation — Release Path Checkpoint

Status: **TECHNICAL RELEASE PATH VALIDATED / STRICT CONTRACT REVALIDATION IN PROGRESS / PRODUCTION ACTIVATION AND DEPLOYMENT NOT AUTHORIZED**

## Canonical conversation capability

CALYX-CONV v3 is merged into backend `main` through PR #798. The cumulative Research Station Ask CALYX stack through RS-15 is merged into Research Station `main` through PR #17.

## Browser/client acceptance gate

Research Station PR #19 adds `CALYX LIVE CONVERSATION — E2E-001`.

Validated client-contract head: `004ae583485b5248da83d3da91f2e8365c16457c`.
CI run: `31525561184`.
Job: `93892890344`.

Result: **PASS** — formatting, lint, full Vitest suite including the client E2E-001 contract, and production build.

A stronger rendered-screen test was subsequently added at `src/components/research/PersistentAskCalyx.e2e.test.tsx`. Its first run and one targeted retry both failed before checkout with `steps=null`; this is runner allocation evidence, not a code verdict. No additional retries are authorized merely to probe allocation.

The validated client contract proves create → ask → reopen → exact-document follow-up → exact persisted source/revision link → Markdown report export with owner-session authentication and permanent non-evidence/non-publication/non-KG-mutation boundaries. This remains mocked transport and is **not** production verification.

## Atomic Research Station schema activation

Backend PR #819 extends the existing guarded activation CLI with the explicit `research-station-conversations` profile.

Previously validated release-tooling head: `7a1a22affde15b9c675da09039d6828bbefdd812`.

Validation on that head:

- CALYX Reasoning Prerequisite Activation Validation — run `31526857397` — **PASS**.
- CALYX Workflow Governance Audit — run `31526857126` — **PASS**.
- BUILD-088E Validation — run `31526857149` — **PASS**.
- PostgreSQL 15 — **PASS**.
- PostgreSQL 16 — **PASS**.
- PostgreSQL 17 / 17.10 — **PASS**.
- historical/default reasoning-prerequisite profile — **PASS**.
- Research Station atomic focused regressions — **9/9 PASS** on PG17.

That validated behavior includes exact migration identities, transaction-scoped advisory serialization on lock `82078079`, one transaction through 101/140 postconditions, complete rollback after intentional failures, canonical rerun no-op, malformed/partial-state refusal, explicit migration-101-only resume, governance/append-only behavior, index/constraint/default/nullability checks, PUBLIC privilege checks, and truthful disposable-vs-production receipts.

## Review hardening — current work

A review audit found that the prior existing-schema CHECK validation used representative fragments and could accept a weakened constraint that still contained one expected token. The function-body and index-definition review findings are already implemented in the validated base; the CHECK review required further hardening.

The current branch therefore adds a strict contract facade around the previously validated activation state machine. The base implementation is preserved byte-for-byte as `scripts/research_station_conversation_activation_base.py`; the public module path now strengthens `inspect_contract()` so every canonical CHECK requires the complete value/bound fragment set to occur in one `pg_get_constraintdef()` result.

New regressions explicitly require fail-closed behavior for:

- a weakened `projects.status` CHECK that permits only `ACTIVE`;
- a neutered conversation append-only function that returns instead of raising;
- an expected index name recreated on the wrong columns.

The validation workflow now compiles/lints/formats both facade and preserved base and executes the strengthened test suite on PostgreSQL 15/16/17.

**This strict-contract delta is not yet claimed validated until its exact-head CI completes.**

## Runtime database-target alignment — new release blocker

Canonical `app.database.get_database_url()` currently prefers `PGHOST` over `DATABASE_URL`. Persistent CALYX-CONV routes inject `get_db`, so conversation persistence uses that shared runtime database selector.

Production schema activation therefore must not proceed until a read-only release check proves that the database targeted by the 101/140 activation workflow is the same database selected by the deployed CALYX-CONV runtime. Applying 101/140 to Neon while a deployed runtime still resolves to a different `PGHOST` database would leave Talk-to-Calyx persistence unavailable even though the migration itself succeeded.

No production environment value was changed. Actual deployed `PGHOST`/`DATABASE_URL` resolution remains **UNVERIFIED**.

## Guarded production-workflow wiring

The existing manual production activation workflow is extended in PR #819 rather than creating a parallel migration framework. It remains `workflow_dispatch` only, refuses non-main dispatch, verifies exact current main, defaults to read-only preflight, requires explicit profile selection, and requires the distinct `APPLY_RESEARCH_STATION_101_140` token for a Research Station apply.

**The production workflow was not dispatched during this work.**

## Production facts already verified read-only

Previous read-only Neon preflight observed PostgreSQL 17.10 and `pgcrypto` 1.3, but no `research_station` schema and therefore no migration-101 prerequisite or migration-140 target tables. No production schema or row mutation occurred.

## Remaining release dependencies

1. Complete exact-head validation of the strict #819 CHECK-contract hardening and resolve only demonstrably addressed review threads.
2. Governed review/merge disposition for #819; do not merge without authorization.
3. Prove deployed CALYX-CONV runtime database target equals the schema-activation target database.
4. Identify and verify the intended production CALYX-CONV application database role and required privileges.
5. Obtain a separate governance authorization for production Research Station schema activation (migration 101 plus migration 140 through the validated atomic profile).
6. Perform post-schema read-only verification.
7. Obtain a separate governance authorization for Research Station/CALYX-CONV deployment and persistent-conversation traffic.
8. Configure deployed Research Station URLs and add its exact origin through the existing CORS allow-list.
9. Run live browser E2E-001 after deployment; only then mark Talk-to-Calyx **PRODUCTION VERIFIED**.

## Governance

NOT AUTHORIZED / NOT PERFORMED:

- production migration 101 or 140;
- production deployment;
- persistent-conversation production traffic;
- Candidate Knowledge promotion;
- scientific publication;
- taxonomy activation;
- production Knowledge Graph mutation.
