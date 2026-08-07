# CI-BASELINE-001 — Current-main blocker repair

## Objective

Repair demonstrated CI blockers directly on the active `main` after the August 7 workflow-governance, supervised-operator, and Atlas releases. This slice ports only the concrete fixes that remain absent from current mainline behavior.

## Implemented

- BUILD-087B full-suite database fallback:
  - the `Full backend suite` step still intentionally unsets `TEST_DATABASE_URL`;
  - it now receives an explicit `DATABASE_URL` for the already-provisioned PostgreSQL service database;
  - this prevents psycopg from falling back to an unintended local role/database.
- Scientific interpretation repository registry typing:
  - `TABLES` is explicitly `ClassVar[dict[str, tuple[str, str, str]]]`;
  - the required `packet` mapping remains present;
  - unused ID-field unpacking is explicit;
  - fingerprint lookup uses `dict.get()` without semantic change.
- Design planning repository registry typing:
  - `TABLES` is explicitly `ClassVar[dict[str, str]]`;
  - the required `product_request` mapping remains present.
- Focused regression tests assert both historically sensitive registry entries and the BUILD-087B full-suite database fallback.
- Dedicated compile, Ruff, pytest, and diff-hygiene validation workflow.

## Release recovery

Original PR #534 was created against an earlier current-main point, received the relevant Ruff repair, but later drifted behind active `main` and became non-mergeable. This replacement branch `fix/ci-baseline-001-current-main-r2` was created directly from the post-Atlas release mainline and ports the small six-file change set instead of forcing the stale branch.

## Validation

Fresh executable CI on the exact replacement head is required before merge. No prior stale-branch success is treated as sufficient for this release branch.

## Governance

This repair changes CI/runtime typing only. It does not deploy, publish scientific knowledge, activate taxonomy, mutate production databases, mutate the production Knowledge Graph, or disclose credentials.
