# Brain — CALYX Runtime / Migration Database Target Gate

Status: IMPLEMENTED / NON-PRODUCTION VALIDATION

## Objective

Before Research Station migrations 101 and 140 can be considered for production authorization, prove that the PostgreSQL database selected by the deployed Calyx runtime is the same logical database targeted by the guarded migration workflow.

## Why this gate exists

Canonical `app.database.get_database_url()` currently prefers `PGHOST`/`PG*` when `PGHOST` is present and falls back to `DATABASE_URL` otherwise. The guarded migration workflow targets `DATABASE_URL`. Therefore schema activation is not sufficient evidence by itself unless runtime and migration targets are proven equal.

## Validation mechanism

`scripts/verify_calyx_runtime_migration_database_target.py`:

- obtains the runtime URL through canonical `app.database.get_database_url()`;
- obtains the migration target from `DATABASE_URL`;
- never prints either raw URL or credentials;
- connects to both targets with PostgreSQL `default_transaction_read_only=on`;
- verifies the session is read-only;
- records sanitized host/port/database, database OID, PostgreSQL version, server address/port, current user, optional cluster system identifier, and canonical sentinel relation OIDs;
- accepts equality when either the sanitized connection identity is identical or cluster-system-identifier + database OID + database name prove the same logical database;
- fails closed when equality cannot be proven or sentinel relation identities disagree;
- emits a hashed JSON receipt;
- permanently records production DB mutation, publication, and Knowledge Graph mutation authorization as false.

## Disposable CI contract

The workflow provisions PostgreSQL 17 and proves:

1. runtime and migration DSNs resolving to the same database PASS;
2. the same runtime configuration paired with a different migration database returns exit code 2 and `RUNTIME_MIGRATION_DATABASE_TARGET_NOT_PROVEN_EQUAL`;
3. when `PGHOST` is absent, runtime `DATABASE_URL` fallback and migration `DATABASE_URL` resolve identically;
4. unit regressions cover different endpoints on the same observed cluster/database and fail-closed behavior when cross-host equality is unprovable.

## Production state

UNVERIFIED by this branch. No production credentials are provided to PR CI and no production database query is made by this workflow.

A future trusted read-only production preflight must execute this verifier in the deployed production configuration or an equivalently faithful secret/environment context before any 101→140 activation authorization.

## Governance

This gate does not change runtime database selection, migration bytes, Brain schema, publication controls, Candidate Knowledge authority, or Knowledge Graph authority. It performs no production mutation and grants no migration/deployment authority.
