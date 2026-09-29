# Engineering Memory activation readiness

Status: **staging validation only; production activation blocked**.

The readiness proof runs solely against a disposable PostgreSQL 16 service in
GitHub Actions. It uses synthetic operational records, refuses non-loopback
hosts or databases without the `engineering_memory_ephemeral_` prefix, and
requires an explicit `ENGINEERING_MEMORY_EPHEMERAL_VALIDATION=1` sentinel.

## Proof contract

The validator proves:

- forward migration and repeated-forward idempotency;
- all three expected tables exist;
- secret and protected-locality redaction before persistence;
- workspace-scope isolation and bounded retrieval;
- measured zero remains distinct from unavailable telemetry;
- invalidated lessons are excluded;
- every lesson remains `non_scientific_evidence`;
- downgrade removes all three tables, then re-upgrade succeeds; and
- final cleanup applies the downgrade, including after a failed assertion.

The report never prints the database URL, credentials, synthetic secret, or
record content. It always declares `scientific_state_changed: false` and keeps
`production_activation` blocked pending an owner checkpoint.

## Activation checkpoint (not authorized here)

No production migration, deployment, credential use, or scientific-state
change is performed by this workflow or validator. A later production proposal
must separately identify the exact target, backup/restore evidence, migration
window, monitoring owner, rollback trigger, and owner approval.

Rollback remains `migrations/082_engineering_memory_downgrade.sql`, executed in
the documented dependency order: retrievals, lessons, then runs.
