# CI-BASELINE-001 — Harvester environment repair

## Demonstrated failure

The current-main broad backend diagnostic reported 32 failures. Harvester safety failures included two environment-specific problems in the shared CI PostgreSQL service:

1. `harvesters.state_helper` appends `sslmode=require` when the database URL does not specify an SSL mode. The ephemeral GitHub Actions PostgreSQL service does not provide SSL, so test checkpoint reads failed before the safety logic could be evaluated.
2. BUILD-105 optional safety telemetry writes target `oc_admin.harvest_safety_state`, but the broad-suite database did not provision that schema/table. This produced repeated missing-relation warnings and obscured the actual safety assertions.

These are CI-environment defects, not grounds to weaken production SSL behavior or production persistence requirements.

## Repair

The BUILD-087B broad diagnostic now:

- uses an explicit local-only `?sslmode=disable` DATABASE_URL for the ephemeral GitHub Actions PostgreSQL service;
- provisions `oc_admin.harvest_safety_state` with the BUILD-105 telemetry contract before the broad diagnostic;
- leaves focused BUILD-087B and BUILD-082–087 database URLs unchanged;
- leaves the broad suite non-blocking while Issue #524 remains open.

## Governance

This change modifies validation infrastructure only. It does not alter production database URLs, production SSL behavior, deployment configuration, harvester execution authority, taxonomy activation, publication authority, or production Knowledge Graph mutation.

## Validation target

The exact branch head must pass the blocking BUILD-087B focused/regression gates and BUILD-088E. The broad diagnostic must execute and be compared with the prior baseline of `32 failed, 1963 passed, 16 skipped`. Any remaining harvester failures are treated as independent code/test-isolation defects and repaired separately rather than hidden.
