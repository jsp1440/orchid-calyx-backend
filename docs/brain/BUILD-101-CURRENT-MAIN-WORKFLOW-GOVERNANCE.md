# BUILD-101 — Current-main Workflow Governance

Date: 2026-08-07
Authoritative PR: #566
Branch: `feature/workflow-governor-current-main`

## Objective

Restore the workflow-governance auditor on current `main` without carrying forward the conflicted history of PR #423. The auditor identifies routine owner-operated GitHub Actions bottlenecks while preserving legitimate destructive or irreversible confirmation gates, then supports deliberate conversion of safe routine checks to automatic execution.

## Implemented

- dependency-free Python auditor across `.github/workflows/*.yml` and `.yaml`;
- trigger classification into `AUTOMATIC`, `AUTOMATIC_WITH_RECOVERY`, `OWNER_BOTTLENECK`, `DESTRUCTIVE_GATED`, and `UNTRIGGERED_OR_UNRECOGNIZED`;
- explicit differentiation between routine manual-only workflows and production workflows with confirmation gates;
- explicit recognition of the BUILD-051 `apply_migration` production dispatch as a destructive governance gate;
- JSON and Markdown inventory output;
- focused regression tests for routine manual bottlenecks, automatic-with-recovery workflows, explicit confirmation gates, and the production migration switch;
- daily, pull-request, push, and manual-recovery auditor triggers;
- job-summary publication and retained report artifacts;
- compile, Ruff, pytest, and report-generation validation;
- automatic daily runner-health probe with manual recovery retained;
- automatic daily deployed read-only preflight with manual recovery retained.

## Recovery from stale PR #423

The original branch became non-mergeable against current `main`. Once hosted runner execution resumed, rerun `31122274890` exposed a workflow defect: the job invoked pytest without installing it, so no auditor tests ran and downstream report steps failed because the inventory was never generated.

The current-main replacement fixes that directly by installing `pytest` and `ruff`, setting `PYTHONPATH: .`, compiling and linting the focused surface, running the regression suite, and generating diagnostics under `if: always()` so a test failure does not erase the audit evidence. Missing report files degrade to a warning/summary message rather than generating misleading secondary failures.

The first successful current-main auditor run, `31217132595`, validated the implementation and audited 192 workflows. It identified three manual-only items: BUILD-051 Production Activation, CALYX-BRAIN-002 Runner Probe, and CALYX Deployed Preflight Smoke.

## Automation-debt reduction

Each finding was reviewed against its actual behavior rather than automatically changing every manual workflow:

- `BUILD-051 Production Activation` can apply a migration to the production database. It remains manual and is now correctly classified `DESTRUCTIVE_GATED` because the `apply_migration` dispatch switch is an explicit production-mutation choice.
- `CALYX-BRAIN-002 Runner Probe` is read-only runner health telemetry. It now runs daily on a schedule and retains `workflow_dispatch` for recovery.
- `CALYX Deployed Preflight Smoke` performs a read-only authenticated deployed-backend preflight and uploads evidence. It now runs daily on a schedule and retains `workflow_dispatch` for recovery.

Post-conversion auditor run `31217349509` completed successfully across dependency setup, compile, Ruff, focused tests, inventory generation, job-summary publication, artifact upload, boundary recording, and cleanup. The resulting inventory is:

- total workflows: 192;
- `AUTOMATIC`: 98;
- `AUTOMATIC_WITH_RECOVERY`: 93;
- `DESTRUCTIVE_GATED`: 1;
- `OWNER_BOTTLENECK`: 0.

The changed deployed-preflight surface also passed dedicated `CALYX Live Preflight Evidence Validation` run `31217349508`, including Ruff and focused pytest validation.

## Governance boundary

The auditor is read-only. It does not dispatch, disable, delete, edit, approve, merge, deploy, publish, activate taxonomy, mutate production data, or weaken explicit destructive-operation confirmation gates. The production migration remains owner-gated by design. Merge/release of PR #566 remains an explicit governance decision.
