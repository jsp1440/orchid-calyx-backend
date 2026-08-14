# CALYX Runtime / Migration Database Target — Current-Main Validation

Status: **VALIDATED READ-ONLY IN DISPOSABLE POSTGRESQL / READY FOR REVIEW / PRODUCTION TARGET STILL UNVERIFIED**

## Integration authority

PR #962 is the clean current-main reconstruction of the read-only runtime-vs-migration PostgreSQL target-equivalence gate.

Validated code head: `475f4e77e7075f41816aa5f1efe98f88194dfaa0`.

Base: canonical main `914c95e1445a99d53fb8e3b733fb83e3c9052222`. Main subsequently advanced by one unrelated Vision Brain documentation commit; there is no target-gate file overlap.

## Executable validation

Exact code-head workflows:

- CALYX Runtime Migration Database Target — run `31764776354` — **PASS**.
- BUILD-088E Validation — run `31764776359` — **PASS**.
- CALYX Workflow Governance Audit — run `31764776360` — **PASS**.

The dedicated PostgreSQL 17 job passed:

- compile, Ruff lint and Ruff format;
- unit comparison contracts;
- same runtime/migration target read-only preflight;
- deliberate different-database fail-closed test;
- `DATABASE_URL` fallback identity behavior;
- evidence artifact upload.

## Contract

The verifier derives the runtime target through canonical `app.database.get_database_url()` and the migration target from `DATABASE_URL`. It opens both connections with PostgreSQL `default_transaction_read_only=on`, verifies read-only state, and records sanitized target observations without raw DSNs or credentials.

Equality is fail-closed using configured target identity plus live observations such as database OID, optional cluster system identifier, and canonical sentinel relation identities. It rejects observed cluster/database/sentinel conflicts and refuses to claim equality when equivalence cannot be proven.

The receipt permanently records production database mutation, publication, and Knowledge Graph mutation authority as false.

## Relationship to atomic schema activation

PR #960 independently owns the atomic migration 101→140 activation mechanism and is executable-green on PostgreSQL 15/16/17. The two release proofs remain intentionally separate:

1. #962 proves the runtime and migration targets are the same database.
2. #960 proves migrations 101 and 140 can be applied atomically and safely to the selected database.

Neither PR authorizes production mutation.

## Production status

The actual deployed CALYX runtime-vs-migration target remains **UNVERIFIED IN PRODUCTION**. This PR's automated workflow uses disposable PostgreSQL only and does not receive production credentials.

A protected trusted-main read-only preflight in the deployment-equivalent environment remains required before any production schema-activation authorization.

NOT AUTHORIZED / NOT PERFORMED:

- production migration 101 or 140;
- production database mutation;
- production deployment;
- persistent-conversation production traffic;
- Candidate Knowledge promotion;
- scientific publication;
- taxonomy activation;
- production Knowledge Graph mutation.
