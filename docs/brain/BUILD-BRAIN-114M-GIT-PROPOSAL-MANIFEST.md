# BUILD-BRAIN-114M — Evidence-bound Git proposal manifest

## Objective

Advance Calyx from validated autonomous engineering work toward Git/PR proposal readiness without granting Git or GitHub mutation authority. BUILD-BRAIN-114M converts a **durably persisted authoritative isolated-patch execution** plus successful persisted external-sandbox validation evidence into a deterministic reviewable proposal manifest.

## R1 trust correction — persisted patch execution

A post-merge trust audit found that the original v1 manifest authenticated sandbox validation receipts against durable supervisor records but still accepted the isolated patch receipt as a caller-supplied mapping. Because the executor key and output checksum are caller-computable, a fabricated patch receipt could seed a formally valid v1 manifest without proving that the authoritative program worker actually completed that patch.

R1 closes that gap using the existing Calyx program-job persistence boundary:

- `PersistedPatchExecutionService` resolves a concrete `CalyxProgramJob` through a SQLAlchemy session;
- the row must be persistent, `completed`, outcome `DELIVERED`, mutating, and use the exact `isolated_workspace_patcher` role;
- `LeaseExecutionBridge` now persists immutable receipt identity (`assignment_id`, `program_id`, `job_key`) in `evidence_json` alongside executor key, state, input checksum, output checksum, output, evidence URIs, and blocker;
- the resolver requires those persisted receipt identities to match the exact program-job row, rejects malformed input checksums, requires executor key `isolated_workspace_patcher_v1`, delivered state, no blocker, and a recomputable output checksum;
- persisted job repository/branch must exactly match receipt output repository/branch;
- the persisted job input manifest is parsed and its exact patch paths, preimage hashes, UTF-8 postimage SHA-256 values, creation flags, byte sizes, file count, and total bytes must match the receipt output; a coherently rehashed but input-divergent output therefore still fails closed;
- the output must still prove authoritative isolated-workspace patch mode, execution, disposable isolation, and no pre-existing commit;
- the proposal builder accepts only `patch_program_job_id`; the old caller-supplied `patch_receipt=` authority path is removed;
- the manifest schema is advanced to `calyx-git-proposal-manifest-v2` and binds `patch_program_job_id` into the manifest digest.

The effective trust chain is therefore **persisted governed job inputs → exact program-job row → exact persisted execution-receipt identity → authoritative isolated patch executor → input/output-consistent patch evidence → manifest v2**.

This means pre-fix v1 manifests cannot silently satisfy the hardened downstream review/authorization path. Draft BUILD-BRAIN-114N/114P/114O and later owner-signature/planning layers must consume v2 and re-bind the durable patch job identity before any can be merged.

## Existing validation trust

114M continues to require persisted supervisor-record authentication for each external validation receipt. `SandboxSupervisorService.get_completed_by_digest()` must resolve an already completed durable record whose repository, branch, commit, preset, targets, timeout, receipt digest, policy digest, authorization ID, and evidence URI match exactly. Allowed sandbox-policy digests remain explicit.

Every changed Python postimage requires exact Ruff coverage. Every changed Python test requires exact pytest coverage by `(path, postimage SHA-256)`. Proposed branches remain confined to valid `autonomy/proposal/*` Git ref names without invoking Git or a shell.

## Permanent non-authorities

BUILD-BRAIN-114M performs no Git command, commit, branch creation, push, pull-request creation, merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation. It stores no credentials and performs no network calls. Both durable-evidence resolvers are read-only.

## Validation contract

The dedicated BUILD-BRAIN-114M workflow compiles and lints the shared execution bridge, `git_proposal_manifest.py`, `persisted_patch_execution.py`, supervisor persistence, and both focused test files. Tests include real in-memory-SQLite program-job persistence through `LeaseExecutionBridge`, missing/wrong-role/wrong-executor/mismatched-identity/tampered-output rejection, coherently rehashed output rejection when governed inputs differ, persisted receipt-row identity mismatch rejection, malformed input-checksum rejection, manifest-v2 determinism, removal of the caller patch-receipt path, persisted supervisor validation, exact Ruff/pytest coverage, and Git branch rules.

Static CI assertions require manifest v2, `patch_program_job_id`, absence of `patch_receipt` in the builder source, persisted patch and validation checks, the three receipt identity fields in `LeaseExecutionBridge`, input/output matching, and permanent non-mutation flags.

Canonical CI incident #481 currently causes repository jobs to terminate before step 1 with `steps=null`; temporary zero-dependency diagnostic PR #690 and later ubuntu-slim diagnostic #698 proved the same failure without application code or third-party actions. Such runs provide no code verdict. R1 remains draft/unmerged until executable validation resumes and passes.
