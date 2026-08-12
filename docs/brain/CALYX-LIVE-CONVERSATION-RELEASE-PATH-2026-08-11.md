# CALYX Live Conversation — Release Path Checkpoint

Status: **TECHNICAL RELEASE PATH VALIDATED / STRICT CONTRACT + DATABASE-TARGET GUARD PENDING EXECUTABLE REVALIDATION / PRODUCTION ACTIVATION AND DEPLOYMENT NOT AUTHORIZED**

## Canonical conversation capability

CALYX-CONV v3 is merged into backend `main` through PR #798. The cumulative Research Station Ask CALYX stack through RS-15 is merged into Research Station `main` through PR #17.

## Browser/client acceptance gate

Research Station PR #19 adds `CALYX LIVE CONVERSATION — E2E-001`.

Validated client-contract head: `004ae583485b5248da83d3da91f2e8365c16457c`.
CI run: `31525561184`.
Job: `93892890344`.

Result: **PASS** — formatting, lint, full Vitest suite including the client E2E-001 contract, and production build.

A stronger rendered-screen test now exists at `src/components/research/PersistentAskCalyx.e2e.test.tsx`. Relative to the validated head, the newer Research Station delta is test/documentation only; application runtime files are unchanged. Its current hosted run terminates before checkout with `steps=null`, so no executable claim is made for that rendered-screen test yet and blind retries are not used.

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

A review audit found that prior existing-schema CHECK validation could accept weakened constraints and that presentation-level index matching could report canonical PostgreSQL indexes missing.

The branch preserves the previously validated state machine in `scripts/research_station_conversation_activation_base.py` and strengthens the public facade. The facade now requires complete canonical CHECK fragment groups and normalizes PostgreSQL index rendering differences such as schema qualification, `USING btree`, and whitespace while continuing to require the exact named index plus its expected columns/predicate.

Regressions require fail-closed behavior for:

- a weakened `projects.status` CHECK;
- a neutered conversation append-only function;
- an expected index name recreated on the wrong columns;
- canonical migration-101-only resume by applying only migration 140.

The latest backend hosted runs for this strict delta terminate before step 1 with `steps=null`; therefore **the strict facade remains implementation-complete but exact-head executable validation is pending runner recovery**. The open CHECK-semantics P1 review thread remains unresolved until that executable proof exists.

## Runtime database-target alignment

Canonical `app.database.get_database_url()` currently prefers `PGHOST` over `DATABASE_URL`, while the guarded 101/140 activation profile targets `DATABASE_URL`. Conversation persistence uses the shared runtime database selector, so applying migrations to a different database would produce a false-success release.

PR #819 now adds `scripts/verify_calyx_runtime_database_target.py`, a non-mutating fail-closed release guard. It compares an explicitly supplied deployed-runtime DSN (`CALYX_RUNTIME_DATABASE_URL`) with the migration `DATABASE_URL` by PostgreSQL host, port, and database identity. Credentials may differ because the migration and application roles may legitimately differ. It emits only SHA-256 target fingerprints and never logs passwords.

The protected production activation workflow now runs this guard before **any** `research-station-conversations` preflight or apply. Missing runtime-target evidence or a target mismatch blocks the workflow. The disposable validation workflow includes unit coverage for matching targets, host/database mismatches, default-port normalization, invalid DSNs, and a same-target rehearsal.

This closes the code-side fail-open path, but actual deployed runtime target evidence is still **UNVERIFIED** until the production environment supplies `CALYX_RUNTIME_DATABASE_URL` from the real deployed Calyx runtime configuration. No production environment setting was changed.

## Guarded production-workflow wiring

The existing manual production activation workflow is extended in PR #819 rather than creating a parallel migration framework. It remains `workflow_dispatch` only, refuses non-main dispatch, verifies exact current main, defaults to read-only preflight, requires explicit profile selection, requires runtime/migration target identity for Research Station operations, and requires the distinct `APPLY_RESEARCH_STATION_101_140` token for an apply.

**The production workflow was not dispatched during this work.**

## Production facts already verified read-only

Previous read-only Neon preflight observed PostgreSQL 17.10 and `pgcrypto` 1.3, but no `research_station` schema and therefore no migration-101 prerequisite or migration-140 target tables. No production schema or row mutation occurred.

## Remaining release dependencies

1. Recover executable backend hosted CI and complete exact-head PG15/16/17 validation of the strict #819 contract + database-target guard.
2. Resolve the remaining CHECK-semantics P1 only after that exact-head proof.
3. Governed review/merge disposition for #819; do not merge without authorization.
4. Supply read-only evidence of the actual deployed CALYX runtime target and prove its fingerprint matches the migration target.
5. Identify and verify the intended production CALYX-CONV application database role and required privileges.
6. Obtain separate governance authorization for production Research Station schema activation (migration 101 plus migration 140 through the validated atomic profile).
7. Perform post-schema read-only verification.
8. Obtain separate governance authorization for Research Station/CALYX-CONV deployment and persistent-conversation traffic.
9. Configure deployed Research Station URLs and add its exact origin through the existing CORS allow-list.
10. Run live browser E2E-001 after deployment; only then mark Talk-to-Calyx **PRODUCTION VERIFIED**.

## Governance

NOT AUTHORIZED / NOT PERFORMED:

- production migration 101 or 140;
- production deployment;
- persistent-conversation production traffic;
- Candidate Knowledge promotion;
- scientific publication;
- taxonomy activation;
- production Knowledge Graph mutation.
