# BUILD-BRAIN-114M — Evidence-bound Git proposal manifest

## Objective

Advance Calyx from validated autonomous engineering work toward Git/PR proposal readiness without granting Git or GitHub mutation authority. BUILD-BRAIN-114M converts a durably persisted authoritative isolated-patch execution plus successful persisted external-sandbox validation evidence into a deterministic reviewable proposal manifest.

## Hardened trust root

The current implementation closes the caller-supplied patch-receipt gap, assignment-capability integration gap, and same-process lease-completion recoverability gap:

- `PersistedPatchExecutionService` resolves an exact persistent `CalyxProgramJob` row and requires delivered status, the `isolated_workspace_patcher` role, mutating intent, exact receipt identity, the registered isolated patch executor, canonical assignment input checksum, canonical output checksum, and exact governed input/output agreement;
- `LeaseExecutionBridge` persists `assignment_id`, `program_id`, and `job_key` with execution receipt evidence;
- `assignment_inputs_for_program_job()` is the single canonical durable input constructor;
- `workspace_write` is issued only for the isolated patch role with explicit durable `mutating=True`; ordinary roles retain the safe validation/receipt/evidence capabilities only;
- the normal deterministic program cycle can produce the authoritative persisted patch evidence consumed by the manifest builder;
- `IsolatedWorkspacePatchExecutor` retains exact preimage bytes in a process-local rollback journal after mutation and before durable lease completion;
- `run_deterministic_program_cycle()` finalizes that journal only after `LeaseExecutionBridge.complete_from_receipt()` succeeds, and restores the preimage before returning an error when lease/database/runtime completion fails;
- `GitProposalManifestBuilder` accepts only `patch_program_job_id`, removing caller-supplied `patch_receipt` authority;
- manifest schema v2 binds the durable patch job identity, patch output checksum, exact proposed changes, persisted supervisor validation evidence, and proposal metadata;
- every changed Python postimage requires exact Ruff evidence and every changed Python test requires exact pytest evidence;
- proposal branches are restricted to valid `autonomy/proposal/*` refs without invoking Git or a shell.

The effective trust chain is:

`persisted governed job inputs → explicit durable mutation intent → role-scoped workspace capability → exact preimage journal → canonical assignment input checksum → exact program-job row → exact persisted execution-receipt identity → registered isolated patch executor → input/output-consistent isolated workspace mutation → durable lease completion or preimage rollback → manifest v2`.

## Current-main R3 reconstruction

PR #772 / branch `fix/brain-114m-r3-current-main` is the authoritative current-main trust root. Historical/current-parent branches #761, #762, #763, #765, #766, #767 and attempted #771 were closed unmerged because they were rooted in superseded ancestry. Downstream review, authorization, signature and execution-plan branches are not authoritative unless reconstructed on the accepted current trust root.

## Institutional status

**FACT** — The earlier private hosted-runner zero-step incident is no longer the active blocker. Hosted Ubuntu runners are executing checkout, Python setup, dependency installation, compilation, lint, formatting, tests and governance checks.

**IMPLEMENTED** — Same-process recoverability now couples isolated workspace mutation to durable lease completion. Existing files are restorable from exact preimage bytes; newly created files are removable; rollback is idempotent; successful durable completion discards rollback material.

**VALIDATED** — Exact head `19e3a5c52e75b78be3c6b1b89de2028ae4fa6257` completed all eight applicable workflows successfully on 2026-08-09:

- BUILD-BRAIN-114M Git Proposal Manifest Validation — run `31323902553`;
- BUILD-BRAIN-108-113A Validation — run `31323902564`;
- BUILD-BRAIN-114A Validation — run `31323902524`;
- BUILD-BRAIN-114C Validation — run `31323902549`;
- BUILD-BRAIN-114I Safe Subset — run `31323902560`;
- CALYX-AGENT-003 Validation — run `31323902545`;
- BUILD-088E Validation — run `31323902544`;
- CALYX Workflow Governance Audit — run `31323902574`.

The dedicated BUILD-BRAIN-114M gate passed compilation, Ruff lint, Ruff formatting, focused proposal/rollback regressions, non-mutation/evidence-authority assertions, and diff hygiene.

**BLOCKED** — PR #772 still has an unresolved P1 review thread requesting recoverability before `workspace_write` is considered merge-ready. The implementation now addresses the stated lease/database completion failure path, but reviewer acknowledgement remains a merge gate.

**UNVALIDATED / REMAINING RISK** — The rollback journal is process-local. A hard process/container crash after filesystem mutation but before durable lease completion can destroy in-memory preimage state. The workspace is explicitly disposable, but crash-safe recovery would require a durable journal or deterministic workspace reconstruction/reconciliation. Do not describe BUILD-BRAIN-114M as crash-atomic until that path is implemented and tested.

## Permanent non-authorities

BUILD-BRAIN-114M performs no Git command, branch creation, commit, push, pull-request creation, merge, deployment, scientific publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation. It stores no credentials and performs no network calls. Isolated workspace mutation is confined to the governed disposable workspace role and requires explicit durable mutation intent.

BUILD-BRAIN-114S—the first real branch/commit/push/open-PR executor—remains outside this implementation boundary and requires explicit owner governance authorization before activation.

## Validation contract

The dedicated workflow compiles and lints the assignment factory, execution bridge, manifest builder, isolated patch executor, program cycle, persisted patch resolver, supervisor persistence, and focused regressions. Tests cover role-scoped `workspace_write`, exact rollback of existing and newly created files, rollback idempotency, successful-finalization behavior, persistent receipt identity, wrong-role/wrong-executor rejection, repository/branch mismatch, malformed or wrong input checksums, coherently rehashed but input-divergent outputs, manifest-v2 determinism, removal of caller patch-receipt authority, persisted supervisor validation, exact Ruff/pytest coverage, and Git branch rules. Static assertions preserve the permanent non-mutation boundary.
