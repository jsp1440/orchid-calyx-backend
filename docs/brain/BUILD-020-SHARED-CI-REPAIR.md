# BUILD-020 — Shared CI Repair Validation Record

## Scope

PR #509 repairs shared CI blockers affecting BUILD-087B, BUILD-089A/B/C, and BUILD-090B/C validation lanes.

## Intended corrections

- preserve an explicit PostgreSQL validation URL through regression matrices instead of deliberately unsetting `TEST_DATABASE_URL` and falling back to the nonexistent `test` role;
- correct Ruff violations in `app/design_intelligence`;
- correct Ruff violations in `app/design_planning` and BUILD-090C tests;
- preserve FastAPI dependency defaults while documenting the required lint exception;
- retain repository-wide backend-suite visibility without making unrelated historical baseline failures a false BUILD-087B release gate.

## First authoritative execution

The original automation-authored head returned `action_required` with no executed jobs. An owner-authored synchronization commit then caused all seven affected workflows to execute.

Results on head `4a6812e5d05326faf22346c83c7a8a0f8b28bbf3`:

- BUILD-088E: passed.
- BUILD-089A: passed.
- BUILD-089C: passed.
- BUILD-090B: passed.
- BUILD-087B: focused and BUILD-082–087 regression tests passed; repository-wide suite failed on unrelated historical baseline debt.
- BUILD-089B: focused PostgreSQL validation passed; regression failed because the workflow explicitly removed `TEST_DATABASE_URL`, causing BUILD-086 tests to connect as nonexistent role `test`.
- BUILD-090C: all functional and PostgreSQL tests passed; Ruff found two deterministic import-order violations in test files.

## Remediation

1. BUILD-089B no longer removes `TEST_DATABASE_URL`; its regression matrix now runs against the workflow's isolated PostgreSQL service.
2. BUILD-090C import ordering is normalized in both reported test files.
3. BUILD-087B retains focused PostgreSQL validation and the BUILD-082–087 regression matrix as blocking gates. The repository-wide backend suite is retained as an informational, non-gating audit because it currently combines unrelated legacy route expectations, deliberate expected-failure certification tests, optional async-test dependency gaps, schema assumptions from newer modules, and other cross-lane baseline debt.
4. BUILD-087B installs `pytest-asyncio` so the informational baseline produces a more accurate signal rather than failing simply because the async pytest plugin is absent.
5. Repository-wide baseline restoration is tracked separately in issue #524; the informational audit remains visible and is not represented as passing.

The informational repository-wide audit must not be represented as passing until its separately tracked baseline debt is repaired. Making it non-gating does not waive the focused or historical BUILD-082–087 regression gates.

## Final synchronization

After the last BUILD-090C Ruff correction, automation authored head `826ac32d7cb3bb4c273d42eba004e66dc17054f8`, causing GitHub to return `action_required` before creating workflow jobs. This owner-authored documentation-only commit intentionally triggers authoritative validation of that exact functional code state. No validation conclusion from an earlier head is carried forward.

## Validation rule

PR #509 remains unmerged unless BUILD-087B, BUILD-088E, BUILD-089A/B/C, and BUILD-090B/C all complete successfully on the final unchanged owner-authored head. The BUILD-087B repository-wide informational audit may report failures without changing the lane verdict, provided the focused and regression gates pass.

## Governance

This repair changes CI configuration, test formatting, and validation semantics only. It grants no deployment, publication, taxonomy activation, credential, automatic merge, or production Knowledge Graph authority.
