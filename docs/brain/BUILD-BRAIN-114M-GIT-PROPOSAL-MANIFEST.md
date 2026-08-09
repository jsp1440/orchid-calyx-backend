# BUILD-BRAIN-114M — Evidence-bound Git proposal manifest

## Objective

Advance Calyx from validated autonomous engineering work toward Git/PR proposal readiness without granting Git or GitHub mutation authority. BUILD-BRAIN-114M converts a durably persisted authoritative isolated-patch execution plus successful persisted external-sandbox validation evidence into a deterministic reviewable proposal manifest.

## Hardened trust root

The current implementation closes the original caller-supplied patch-receipt gap and the later assignment-capability integration gap:

- `PersistedPatchExecutionService` resolves an exact persistent `CalyxProgramJob` row and requires delivered status, the `isolated_workspace_patcher` role, mutating intent, exact receipt identity, the registered isolated patch executor, canonical assignment input checksum, canonical output checksum, and exact governed input/output agreement;
- `LeaseExecutionBridge` persists `assignment_id`, `program_id`, and `job_key` with execution receipt evidence;
- `assignment_inputs_for_program_job()` is the single canonical durable input constructor;
- `workspace_write` is issued only for the isolated patch role with explicit durable `mutating=True`; ordinary roles retain the safe validation/receipt/evidence capabilities only;
- the normal deterministic program cycle can produce the authoritative persisted patch evidence consumed by the manifest builder;
- `GitProposalManifestBuilder` accepts only `patch_program_job_id`, removing caller-supplied `patch_receipt` authority;
- manifest schema v2 binds the durable patch job identity, patch output checksum, exact proposed changes, persisted supervisor validation evidence, and proposal metadata;
- every changed Python postimage requires exact Ruff evidence and every changed Python test requires exact pytest evidence;
- proposal branches are restricted to valid `autonomy/proposal/*` refs without invoking Git or a shell.

The effective trust chain is:

`persisted governed job inputs → explicit durable mutation intent → role-scoped workspace capability → canonical assignment input checksum → exact program-job row → exact persisted execution-receipt identity → registered isolated patch executor → input/output-consistent isolated workspace mutation → manifest v2`.

## Current-main R3 reconstruction

PR #772 / branch `fix/brain-114m-r3-current-main` is the authoritative current-main trust root. PR #761 / BUILD-BRAIN-114M-R2 became 11 commits behind current `main`. A merge-base-to-current-main audit found those intervening commits touched Harvester Command Center files and none of the nine BUILD-BRAIN-114M trust-root files, so R3 reapplies the hardened trust-root delta directly on the newer main lineage rather than carrying stale ancestry.

At the current checkpoint, historical/current-parent branches #761, #762, #763, #765, #766, #767 and attempted #771 have been closed unmerged because they are rooted in the superseded #761 lineage. Retargeting #771 directly to #772 produced a non-mergeable 15-file diff, confirming that the downstream ancestry must not be reused mechanically. The next safe dependency path is therefore to rebuild BUILD-BRAIN-114N directly on the exact #772 head, then rebuild 114P, 114O, 114Q and plan-only 114R in order.

No downstream review, authorization, signature or execution-plan branch is authoritative until it is reconstructed on this exact R3 root.

## Validation state

The pre-step hosted-runner incident was traced to the account-level GitHub Actions budget hard stop: the $25 monthly Actions budget had reached 100%, so private-repository jobs were terminated before step 1. The Actions budget was raised to $50, restoring private hosted-runner allocation.

Executable validation on head `23d03cb2a006a910127cabf0d41ed8e32f31a4e8` then proved the runner path healthy: checkout, Python 3.12 setup, dependency installation and compilation all executed. BUILD-BRAIN-114I, BUILD-BRAIN-114A, BUILD-BRAIN-108-113A, BUILD-088E, CALYX Workflow Governance Audit and CALYX-AGENT-003 all passed. The dedicated BUILD-BRAIN-114M lane reached Ruff and failed only because `ruff format --check` identified four formatting-only postimages; `ruff check` itself passed. Commit `cc3da7b5dd145041019ce732c3a766db7a14276f` applied those formatter-prescribed changes without changing the trust model or authority boundary.

Because the formatter commit was authored through Copilot, its automatic workflow runs entered GitHub's `action_required` state without jobs. This documentation checkpoint records that transition and provides a user-authored follow-up head so the exact-head validation suite can execute normally. PR #772 remains draft/unmerged until the new exact-head focused and broad gates complete successfully.

## Permanent non-authorities

BUILD-BRAIN-114M performs no Git command, branch creation, commit, push, pull-request creation, merge, deployment, scientific publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation. It stores no credentials and performs no network calls. Isolated workspace mutation is confined to the already-governed disposable workspace role and requires explicit durable mutation intent.

BUILD-BRAIN-114S—the first real branch/commit/push/open-PR executor—remains outside the authorized implementation boundary and requires an explicit owner governance decision.

## Validation contract

The dedicated workflow compiles and lints the assignment factory, execution bridge, manifest builder, persisted patch resolver, supervisor persistence, and focused regressions. Tests cover role-scoped `workspace_write`, the real deterministic program-cycle isolated patch path, persistent receipt identity, wrong-role/wrong-executor rejection, repository/branch mismatch, malformed or wrong input checksums, coherently rehashed but input-divergent outputs, manifest-v2 determinism, removal of caller patch-receipt authority, persisted supervisor validation, exact Ruff/pytest coverage, and Git branch rules. Static assertions preserve the permanent non-mutation boundary.
