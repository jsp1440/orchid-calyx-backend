# BUILD-BRAIN-114M — Evidence-bound Git proposal manifest

## Objective

Advance Calyx from validated autonomous engineering work toward Git/PR proposal readiness without granting Git or GitHub mutation authority. BUILD-BRAIN-114M converts a **durably persisted authoritative isolated-patch execution** plus successful persisted external-sandbox validation evidence into a deterministic reviewable proposal manifest.

## R1 trust correction — persisted patch execution

A post-merge trust audit found that the original v1 manifest authenticated sandbox validation receipts against durable supervisor records but still accepted the isolated patch receipt as a caller-supplied mapping. Because the executor key and output checksum are caller-computable, a fabricated patch receipt could seed a formally valid v1 manifest without proving that the authoritative program worker actually completed that patch.

R1 closes that gap using the existing Calyx program-job persistence boundary:

- `PersistedPatchExecutionService` resolves a concrete `CalyxProgramJob` through a SQLAlchemy session;
- the row must be persistent, `completed`, outcome `DELIVERED`, mutating, and use the exact `isolated_workspace_patcher` role;
- `LeaseExecutionBridge` persists immutable receipt identity (`assignment_id`, `program_id`, `job_key`) in `evidence_json` alongside executor key, state, input checksum, output checksum, output, evidence URIs, and blocker;
- the resolver requires those persisted receipt identities to match the exact program-job row, requires executor key `isolated_workspace_patcher_v1`, delivered state, no blocker, and a recomputable output checksum;
- persisted job repository/branch must exactly match receipt output repository/branch;
- the persisted job input manifest is parsed and its exact patch paths, preimage hashes, UTF-8 postimage SHA-256 values, creation flags, byte sizes, file count, and total bytes must match the receipt output; a coherently rehashed but input-divergent output therefore still fails closed;
- the output must still prove authoritative isolated-workspace patch mode, execution, disposable isolation, and no pre-existing commit;
- the proposal builder accepts only `patch_program_job_id`; the old caller-supplied `patch_receipt=` authority path is removed;
- the manifest schema is advanced to `calyx-git-proposal-manifest-v2` and binds `patch_program_job_id` into the manifest digest.

## R1 integration correction — executable assignment path

A later integration audit found that the trust resolver was stronger than the runtime path feeding it: `IsolatedWorkspacePatchExecutor` requires `workspace_write`, but the generic governed assignment factory granted only validate/receipt/evidence capabilities. The normal `run_deterministic_program_cycle()` could therefore claim an isolated patch job and then fail before patch execution, while persistence tests could still pass by manually constructing an execution receipt.

R1 now closes that integration gap without broadening authority:

- `assignment_factory.py` keeps the existing safe base capabilities for ordinary roles;
- only `isolated_workspace_patcher` receives the additional `workspace_write` capability;
- its assignment governance mode is `bounded_isolated_workspace_mutation`, while external execution, repository code execution, merge, deployment, publication, and production graph mutation remain false;
- a shared `assignment_inputs_for_program_job()` function is the single canonical constructor for the assignment input object;
- `PersistedPatchExecutionService` recomputes `input_checksum` from that same constructor plus the durable program/job rows and rejects a valid-shape but incorrect SHA-256;
- focused integration coverage creates a disposable Git worktree and isolation marker, creates a real persisted patch job, runs it through `run_deterministic_program_cycle()` with `AuthoritativeExecutorRegistry`, verifies the actual file mutation, then resolves the resulting durable receipt through `PersistedPatchExecutionService`.

This removes the prior test-only shortcut: the normal registered authoritative worker path can now produce the exact persisted patch evidence consumed by manifest v2.

The effective trust chain is therefore **persisted governed job inputs → canonical assignment input checksum → exact program-job row → exact persisted execution-receipt identity → registered isolated patch executor → input/output-consistent isolated workspace mutation → manifest v2**.

This means pre-fix v1 manifests cannot silently satisfy the hardened downstream review/authorization path. BUILD-BRAIN-114N/114P/114O and later owner-signature/planning layers must consume v2 and re-bind the durable patch job identity before any can be merged.

## Existing validation trust

114M continues to require persisted supervisor-record authentication for each external validation receipt. `SandboxSupervisorService.get_completed_by_digest()` must resolve an already completed durable record whose repository, branch, commit, preset, targets, timeout, receipt digest, policy digest, authorization ID, and evidence URI match exactly. Allowed sandbox-policy digests remain explicit.

Every changed Python postimage requires exact Ruff coverage. Every changed Python test requires exact pytest coverage by `(path, postimage SHA-256)`. Proposed branches remain confined to valid `autonomy/proposal/*` Git ref names without invoking Git or a shell.

## Current-main R2 reconstruction

The original R1 branch became stale while unrelated Calyx work advanced `main`. A file-overlap audit from its merge base to current `main` found **zero overlap across the nine R1 files**. R2 therefore rebuilds the same hardened trust root directly on current `main` rather than merging a 17-commit-behind branch. This preserves intervening Brain, conversation, and reasoning-prerequisite work while retaining the exact R1 authority boundaries.

The R2 merge gate is executable exact-head validation on the current-main replacement branch: BUILD-BRAIN-114M focused tests, BUILD-088E, agent/Brain regression lanes selected by the changed surfaces, workflow governance, and an unchanged-head review audit. Downstream 114N/114P/114O branches must be rebuilt on the exact merged R2 head before they are treated as authoritative.

## Permanent non-authorities

BUILD-BRAIN-114M performs no Git command, commit, branch creation, push, pull-request creation, merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation. It stores no credentials and performs no network calls. The isolated patch capability is confined to the already-governed disposable workspace role; both durable-evidence resolvers are read-only.

## Validation contract

The dedicated BUILD-BRAIN-114M workflow compiles and lints the assignment factory, shared execution bridge, `git_proposal_manifest.py`, `persisted_patch_execution.py`, supervisor persistence, and focused tests. Coverage includes real program-job persistence through `LeaseExecutionBridge`, a full `run_deterministic_program_cycle()` isolated-patch integration using a disposable worktree, role-specific `workspace_write` assignment checks, missing/wrong-role/wrong-executor/mismatched-identity/tampered-output rejection, coherently rehashed output rejection when governed inputs differ, persisted receipt-row identity mismatch rejection, malformed input-checksum rejection, valid-shape wrong input-checksum rejection, manifest-v2 determinism, removal of the caller patch-receipt path, persisted supervisor validation, exact Ruff/pytest coverage, and Git branch rules.

Static CI assertions require manifest v2, `patch_program_job_id`, absence of `patch_receipt` in the builder source, persisted patch and validation checks, the three receipt identity fields in `LeaseExecutionBridge`, exact assignment-input checksum verification, isolated-patch-only `workspace_write`, input/output matching, and permanent non-mutation flags.
