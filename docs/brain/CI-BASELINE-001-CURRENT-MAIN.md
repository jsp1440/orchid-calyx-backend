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
- Design-planning lint cleanup uses `Annotated` FastAPI dependency metadata instead of callable defaults and keeps existing request semantics.
- Package-export hygiene removes stale suppression and makes exported planning symbols explicit.
- Focused regression tests assert both historically sensitive registry entries and the BUILD-087B full-suite database fallback.
- Dedicated compile, Ruff, pytest, and diff-hygiene validation workflow.

## Release recovery

Original PR #534 was created against an earlier current-main point, received the relevant Ruff repair, but later drifted behind active `main` and became non-mergeable. Replacement PR #568 (`fix/ci-baseline-001-current-main-r2`) was created directly from the post-Atlas release mainline and ports the demonstrated blocker repair instead of forcing the stale branch.

## Validation status — 2026-08-07

Executable CI on earlier #568 heads established the following before the final cleanup commits:

- the focused CI-BASELINE-001 gate passed;
- BUILD-088E publication-control validation passed;
- workflow-governance validation passed;
- BUILD-090B and BUILD-090C functional/PostgreSQL regression stages passed and then stopped on deterministic Ruff findings in the existing design-planning surface;
- BUILD-087B focused/PostgreSQL and BUILD-082→087 regression stages passed, leaving its full-backend-suite failure as the remaining functional diagnostic target.

The subsequent cleanup commits corrected the demonstrated FastAPI/Ruff findings and preserved the explicit BUILD-087B database fallback. GitHub then returned `action_required` with zero executable jobs on head `6822bc611e62543e7f22d06df6f571153a8992ae`; that state is not treated as validation. This Brain update intentionally records the evidence and triggers a fresh exact-head validation opportunity. Merge remains contingent on executable current-head CI rather than a badge-only assumption.

## Governance

This repair changes CI/runtime typing and request declaration hygiene only. It does not deploy, publish scientific knowledge, activate taxonomy, mutate production databases, mutate the production Knowledge Graph, or disclose credentials.
