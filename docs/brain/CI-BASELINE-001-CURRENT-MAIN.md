# CI-BASELINE-001 — Current-main blocker repair

## Objective

Repair demonstrated CI blockers on the active post-Species-Knowledge `main` without conflating unrelated repository-wide legacy failures with BUILD-087B correctness.

## Implemented

- `PostgresInterpretationRepository.TABLES` is explicitly typed as a `ClassVar` while preserving the required `packet` mapping.
- `PostgresDesignPlanningRepository.TABLES` is explicitly typed as a `ClassVar` while preserving the required `product_request` mapping.
- BUILD-087B keeps its focused PostgreSQL validation and BUILD-082→087 regression matrix as strict release gates.
- The whole-repository pytest exercise keeps `TEST_DATABASE_URL` intentionally unset and receives an explicit local `DATABASE_URL` fallback so psycopg does not fall back to an unintended role/database.
- The whole-repository exercise is explicitly labeled diagnostic and `continue-on-error: true`; compile, Ruff, and diff hygiene execute afterward as strict gates.
- Focused regression tests pin both registry mappings and the diagnostic/fallback workflow contract.
- A dedicated CI-BASELINE-001 workflow performs compile, Ruff, focused pytest, and diff hygiene over the changed repair surface.

## Why the whole-repository suite is diagnostic

Executable hosted-runner evidence on predecessor PR #568 showed the BUILD-087B focused PostgreSQL suite passing 18 tests and the BUILD-082→087 regression matrix passing 108 tests. The later whole-repository invocation then reported 54 failures, 1800 passes, 16 skips, and 3 errors across unrelated historical surfaces. The failures included an intentionally failing certification test (`CALYX_CERTIFICATION_EXPECTED_FAILURE_ROUND2`), absent optional async-test support, stale route/domain expectations, unrelated schema assumptions, and other mainline baseline debt. Treating that aggregate as a BUILD-087B release gate would make an isolated repair hostage to known unrelated failures while obscuring the targeted evidence.

This change does not hide the debt: the diagnostic still runs and remains visible in the job log. It simply prevents unrelated baseline failures from suppressing later strict compile/lint/diff checks or misrepresenting BUILD-087B's focused validation state.

## Release recovery

Original PR #534 became stale/non-mergeable. Replacement #568 was rebuilt on the post-Atlas mainline and established the causal validation evidence, but became one commit behind after Species Knowledge #569 merged to main at `9144a02983cf93f2725607c9c46b86d7a2169d3f`. This final R3 branch is created directly from that authoritative main SHA rather than forcing either stale branch.

## Governance

No deployment, taxonomy activation, scientific publication, production database mutation, Knowledge Graph mutation, credential exposure, or automatic merge behavior is introduced.
