# CALYX CI — occurrence workflow parser repair (#949)

Date: 2026-08-13

## Symptom

The `CALYX Occurrence Consolidated Validation` workflow produced repeated failed runs with zero runner jobs. The failure therefore occurred before occurrence tests executed.

## Root cause boundary

The workflow database configuration surfaced as leading asterisk-prefixed URL scalars. Leading `*` has YAML alias semantics and makes that configuration unsafe at workflow-parse time. The repair removes credential-shaped URL literals from the workflow entirely.

## Repair

The PostgreSQL service now uses local trust authentication inside the isolated GitHub Actions service container. `DATABASE_URL` and `TEST_DATABASE_URL` use libpq key/value DSN syntax (`dbname`, `user`, `host`, `port`) rather than URL syntax. `workflow_dispatch` and the service port are also written with explicit unambiguous YAML forms.

## Scientific invariants

No occurrence persistence logic, taxonomy guard, reconciliation assertion, migration, production database setting, or canonical graph authority is changed by this repair. The workflow continues to compile and lint the occurrence surface, run both PostgreSQL integration test files, run the exact-replay regression, and reject forbidden canonical mutation strings in the occurrence migrations.

## Validation requirement

The repair is complete only if GitHub creates an actual runner job for the workflow and the occurrence test job passes. A zero-job failure is not considered validation.
