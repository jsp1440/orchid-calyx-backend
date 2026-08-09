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

PR #761 / BUILD-BRAIN-114M-R2 became 11 commits behind current `main`. A merge-base-to-current-main audit found that those 11 commits touched only Harvester Command Center files and **none of the nine BUILD-BRAIN-114M trust-root files**. The R3 branch `fix/brain-114m-r3-current-main` therefore rebuilds the exact hardened R2 file set directly on current `main` rather than carrying stale ancestry forward.

The R3 reconstruction preserves the trusted R2 implementation bytes for the trust-root files while retaining every intervening current-main change. The branch is not merge-authorized until its exact unchanged head receives executable focused BUILD-BRAIN-114M validation plus relevant broad regressions and has no unresolved review findings. Zero-step GitHub Actions failures under hosted-runner incident #481 are infrastructure evidence only and are not counted as pass or fail results.

Downstream BUILD-BRAIN-114N/114P/114O/114Q/114R branches must be rebuilt on the exact merged R3 trust root before they are authoritative.

## Permanent non-authorities

BUILD-BRAIN-114M performs no Git command, branch creation, commit, push, pull-request creation, merge, deployment, scientific publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation. It stores no credentials and performs no network calls. Isolated workspace mutation is confined to the already-governed disposable workspace role and requires explicit durable mutation intent.

## Validation contract

The dedicated workflow compiles and lints the assignment factory, execution bridge, manifest builder, persisted patch resolver, supervisor persistence, and focused regressions. Tests cover role-scoped `workspace_write`, the real deterministic program-cycle isolated patch path, persistent receipt identity, wrong-role/wrong-executor rejection, repository/branch mismatch, malformed or wrong input checksums, coherently rehashed but input-divergent outputs, manifest-v2 determinism, removal of caller patch-receipt authority, persisted supervisor validation, exact Ruff/pytest coverage, and Git branch rules. Static assertions preserve the permanent non-mutation boundary.
