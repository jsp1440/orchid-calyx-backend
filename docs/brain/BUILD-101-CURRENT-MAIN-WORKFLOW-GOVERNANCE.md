# BUILD-101 — Current-main Workflow Governance

Date: 2026-08-07
Branch: `feature/workflow-governor-current-main`

## Objective

Restore the workflow-governance auditor on current `main` without carrying forward the conflicted history of PR #423. The auditor identifies routine owner-operated GitHub Actions bottlenecks while preserving legitimate destructive or irreversible confirmation gates.

## Implemented

- dependency-free Python auditor across `.github/workflows/*.yml` and `.yaml`;
- trigger classification into `AUTOMATIC`, `AUTOMATIC_WITH_RECOVERY`, `OWNER_BOTTLENECK`, `DESTRUCTIVE_GATED`, and `UNTRIGGERED_OR_UNRECOGNIZED`;
- explicit differentiation between routine manual-only workflows and production workflows with confirmation gates;
- JSON and Markdown inventory output;
- focused regression tests for routine manual bottlenecks, automatic-with-recovery workflows, and destructive gated workflows;
- daily, pull-request, push, and manual-recovery workflow triggers;
- job-summary publication and retained report artifacts;
- compile, Ruff, pytest, and report-generation validation.

## Recovery from stale PR #423

The original branch became non-mergeable against current `main`. Once hosted runner execution resumed, rerun `31122274890` also exposed a workflow defect: the job invoked pytest without installing it, so no auditor tests ran and downstream report steps failed because the inventory was never generated.

The current-main replacement fixes that directly by installing `pytest` and `ruff`, setting `PYTHONPATH: .`, compiling and linting the focused surface, running the regression suite, and generating diagnostics under `if: always()` so a test failure does not erase the audit evidence. Missing report files degrade to a warning/summary message rather than generating misleading secondary failures.

## Governance boundary

The auditor is read-only. It does not dispatch, disable, delete, edit, approve, merge, deploy, publish, activate taxonomy, mutate production data, or weaken explicit destructive-operation confirmation gates. Its purpose is to surface automation debt so routine owner intervention can be removed deliberately.
