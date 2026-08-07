# CI-BASELINE-001 — Current-main blocker repair

## Objective

Repair demonstrated CI blockers directly on current `main` rather than relying on stale Copilot branches. This slice addresses only failures with concrete prior evidence and preserves all existing scientific/governance boundaries.

## Implemented

- BUILD-087B full-suite database fallback:
  - the `Full backend suite` step still intentionally unsets `TEST_DATABASE_URL`;
  - it now receives an explicit `DATABASE_URL` for the already-provisioned PostgreSQL service database;
  - this prevents psycopg from falling back to a nonexistent local role such as `test`.
- Scientific interpretation repository lint/runtime safety:
  - `TABLES` is explicitly typed as `ClassVar[dict[str, tuple[str, str, str]]]`;
  - the required `packet` mapping remains present;
  - the unused ID-field unpack is made explicit;
  - fingerprint lookup uses `dict.get()` without changing semantics.
- Design planning repository lint/runtime safety:
  - `TABLES` is explicitly typed as `ClassVar[dict[str, str]]`;
  - the required `product_request` mapping remains present.
- Focused regression tests assert that both historically dropped registry entries remain present and that the BUILD-087B full-suite fallback is encoded in the workflow.
- Added a dedicated focused CI workflow covering compile, Ruff, regression tests, and diff hygiene.

## Relationship to stale PRs

This current-main slice supersedes the applicable portion of PR #519 without replaying its stale branch wholesale. PR #519 was based on an older merge base and also carried broad formatting changes across design-intelligence/design-planning modules. This slice ports only the demonstrated blockers that remain absent from current `main`.

## Validation status

The repository is currently affected by GitHub-hosted runner incident #533: backend jobs are terminating before their first step is instantiated. Therefore executable CI success is not claimed until hosted-runner execution resumes. The focused workflow is in place so the repaired surface can be validated immediately when runner allocation is restored.

## Governance

No production deployment, taxonomy activation, publication, credential disclosure, production database mutation, or Knowledge Graph mutation is introduced by this work.
