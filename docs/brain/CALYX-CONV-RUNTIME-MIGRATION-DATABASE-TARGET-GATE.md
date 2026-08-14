# CALYX-CONV — Runtime / Migration Database Target Equivalence Gate

**Status:** read-only validated implementation candidate; no production migration or runtime activation.

## Purpose

Prevent CALYX conversation-schema activation from being authorized against one PostgreSQL target while the deployed runtime is actually configured to use another. The gate treats runtime-target identity and migration-target identity as a separate release authority from the 101→140 atomic schema migration itself.

## Canonical target derivation

The runtime target is derived through the canonical `app.database.get_database_url()` path. This matters because runtime configuration may prefer `PGHOST` / `PG*` settings over `DATABASE_URL`. The migration target is derived independently from `DATABASE_URL`.

A successful schema migration against `DATABASE_URL` therefore does not, by itself, prove that CALYX runtime traffic will use the migrated database.

## Read-only observation contract

The verifier connects independently to the runtime and migration targets with `default_transaction_read_only=on` and verifies the read-only transaction state before collecting identity evidence. It never prints raw DSNs or credentials.

The evidence model includes sanitized configured host/port/database identity, observed database name and OID, server version/address/port, current user, optional PostgreSQL cluster `system_identifier`, and OIDs for canonical sentinel relations when present.

The emitted receipt is hashed and explicitly records that production database mutation, publication, and Knowledge Graph mutation are not authorized or attempted.

## Fail-closed equivalence rules

The gate passes only when target equality can be positively established and no observed identity conflict exists. It blocks on:

- differing observed PostgreSQL cluster system identifiers;
- same-cluster/same-database-name observations with different database OIDs;
- differing canonical sentinel-relation OIDs;
- runtime/migration equality that otherwise cannot be proven;
- failure to enforce read-only preflight state.

Exact configured endpoint equality can support equivalence only when live observations do not contradict it. Cross-endpoint equality requires compatible observed cluster/database identity. The gate never treats mere connection success as proof of target equivalence.

## Disposable validation

The dedicated PostgreSQL 17 workflow proves three operational cases on the exact branch head:

1. identical runtime and migration targets pass the read-only preflight;
2. deliberately different databases fail closed;
3. when `PGHOST` is absent, canonical runtime fallback to `DATABASE_URL` resolves to the migration target exactly.

Compile, Ruff check, Ruff format, focused unit tests, disposable database tests, BUILD-088E, and workflow-governance audit are part of the validation chain.

## Release sequencing

This target-equivalence gate and the atomic 101→140 schema activation are intentionally separate controls. A production schema activation decision should require both:

1. the runtime/migration target gate to prove that CALYX runtime and migration authority point at the same intended database; and
2. the atomic migration preflight/runner to prove the schema transition itself is safe and valid.

Passing either control alone is insufficient production authorization.

## Governance boundary

This implementation performs no production DDL/DML, migration application, deployment, persistent-conversation traffic, Candidate Knowledge promotion, scientific publication, taxonomy activation, Knowledge Graph mutation, credential disclosure, or spending. Any production migration and subsequent durable conversation activation remain separately owner-governed.