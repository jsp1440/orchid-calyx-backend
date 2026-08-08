# CI-BASELINE-001 — Owner audit schema fidelity

## Demonstrated failure

After BUILD-105 harvester isolation reduced the broad diagnostic from 32 to 29 failures, three remaining failures were the same owner-audit path:

- PDF audit generation returned HTTP 503;
- DOCX audit generation returned HTTP 503;
- Markdown audit generation returned HTTP 503.

The PostgreSQL log showed all three failing on the same missing relation: `oc_admin.build051_generated_audits`.

The repository already contains the authoritative idempotent BUILD-051 owner-console migration defining that table and the related owner-operation persistence schema. The broad validation database simply had not applied it.

## Repair

BUILD-087B broad validation now applies `migrations/BUILD-051-owner-operations-console.sql` to its ephemeral `build087_validation` PostgreSQL database before running the repository-wide diagnostic.

This uses the authoritative schema instead of reproducing a partial test-only table definition. The migration is applied only to the disposable GitHub Actions database.

## Governance

This change does not apply or activate a production migration. It does not mutate Neon/Render/production databases, grant owner-operation authority, publish content, activate taxonomy, disclose credentials, or mutate the production Knowledge Graph.

## Validation target

The exact head must pass BUILD-087B focused/regression gates and BUILD-088E. The broad diagnostic must execute and should eliminate the three prior `tests/test_build_062_execution.py` owner-audit generation failures. The prior baseline is `29 failed, 1966 passed, 16 skipped`; the expected directional result is at most 26 failures if no other test interaction changes.
