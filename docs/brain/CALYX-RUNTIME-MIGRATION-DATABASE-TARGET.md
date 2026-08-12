# Brain — CALYX Runtime / Migration Database Target Gate

Status: IMPLEMENTED / NON-PRODUCTION VALIDATION / EXACT-HEAD CI BLOCKED BEFORE STEP 1

## Objective

Before Research Station migrations 101 and 140 can be considered for production authorization, prove that the PostgreSQL database selected by the deployed Calyx runtime is the same logical database targeted by the guarded migration workflow.

## Why this gate exists

Canonical `app.database.get_database_url()` currently prefers `PGHOST`/`PG*` when `PGHOST` is present and falls back to `DATABASE_URL` otherwise. The guarded migration workflow targets `DATABASE_URL`. Historical repository documentation describes the `PGHOST` path as Replit-hosted PostgreSQL, while governed production migration workflows use `DATABASE_URL`. Therefore schema activation is not sufficient evidence by itself unless runtime and migration targets are proven equal.

## Validation mechanism

`scripts/verify_calyx_runtime_migration_database_target.py`:

- obtains the runtime URL through canonical `app.database.get_database_url()`;
- obtains the migration target from `DATABASE_URL`;
- never prints either raw URL or credentials;
- connects to both targets with PostgreSQL `default_transaction_read_only=on`;
- verifies the session is read-only;
- records sanitized host/port/database, database OID, PostgreSQL version, server address/port, current user, optional cluster system identifier, and canonical sentinel relation OIDs;
- accepts equality when exact sanitized configuration identity is compatible with all observed database identities, or when cluster-system-identifier + database OID + database name independently prove the same logical database;
- fails closed when equality cannot be proven;
- fails closed on canonical sentinel relation identity disagreement;
- fails closed when both observations expose different PostgreSQL cluster system identifiers even if host/port/database configuration text is identical;
- fails closed when both observations are on the same observed cluster/database name but return different database OIDs;
- emits a hashed JSON receipt;
- permanently records production DB mutation, publication, and Knowledge Graph mutation authorization as false.

## Regression contract

The unit contract includes:

1. exact configuration identity acceptance when observed identities agree;
2. different connection endpoints accepted only when cluster + database identity independently agree;
3. different database refusal;
4. unprovable cross-host refusal when cluster identity is unavailable;
5. canonical sentinel relation mismatch refusal;
6. exact configuration identity refusal when observed PostgreSQL cluster identifiers disagree;
7. exact configuration identity refusal when the same observed cluster/database name reports a different database OID.

The disposable PostgreSQL 17 workflow additionally exercises same-target, deliberately different-database, and `DATABASE_URL` fallback behavior.

## Exact current validation boundary

PR: #897

Current hardening head before this documentation update: `b9c8454674a9e57962a8f7f16869eafb1bdf2f3e`.

Automatic run `31560794159` / job `94002457928` failed before step 1 with `steps=null`. BUILD-088E and Workflow Governance also failed in the same private-runner allocation condition. Therefore the two newest observed-identity regressions are IMPLEMENTED but not yet EXECUTABLE-GREEN, and this PR must remain Draft/unmerged until a real hosted runner executes them.

Do not blind-rerun this head merely to probe the allocator. A private-repository job with a non-empty step list is the recovery signal.

## Production state

UNVERIFIED by this branch. No production credentials are provided to PR CI and no production database query is made by this workflow.

Repository code/configuration alone cannot establish whether the deployed Render service still has `PGHOST` set. A future trusted read-only production preflight must execute this verifier in the deployed production configuration or an equivalently faithful protected environment before any 101→140 activation authorization.

## Governance

This gate does not change runtime database selection, migration bytes, Brain schema, publication controls, Candidate Knowledge authority, or Knowledge Graph authority. It performs no production mutation and grants no migration/deployment authority.
