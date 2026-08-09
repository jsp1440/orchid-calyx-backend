# BUILD-BRAIN-114M — Evidence-bound Git proposal manifest

## Objective

Advance Calyx from validated autonomous engineering work toward Git/PR proposal readiness without granting Git or GitHub mutation authority. BUILD-BRAIN-114M converts a durably persisted authoritative isolated-patch execution plus successful persisted external-sandbox validation evidence into a deterministic reviewable proposal manifest.

## Hardened trust root

The current implementation closes the caller-supplied patch-receipt gap, assignment-capability integration gap, lease-completion recovery gap, and the hard-process-crash rollback gap:

- `PersistedPatchExecutionService` resolves an exact persistent `CalyxProgramJob` row and requires delivered status, the `isolated_workspace_patcher` role, mutating intent, exact receipt identity, the registered isolated patch executor, canonical assignment input checksum, canonical output checksum, and exact governed input/output agreement;
- `LeaseExecutionBridge` persists `assignment_id`, `program_id`, and `job_key` with execution receipt evidence;
- `assignment_inputs_for_program_job()` is the single canonical durable input constructor;
- `workspace_write` is issued only for the isolated patch role with explicit durable `mutating=True`; ordinary roles retain the safe validation/receipt/evidence capabilities only;
- before any target-file replacement, `IsolatedWorkspacePatchExecutor` writes a checksummed rollback journal into the explicitly disposable isolated worktree, containing exact preimages, before/after hashes, assignment identity, repository, branch, and checkout commit;
- the rollback journal is written atomically, fsynced, retained until durable lease completion, and deleted only after success;
- a new executor process detects an interrupted journal on retry, verifies exact identity and journal checksum, and restores only files still matching the expected before/postimage states;
- unexpected third-party workspace divergence fails closed instead of overwriting unknown changes;
- `run_deterministic_program_cycle()` rolls back before returning an error when lease/database/runtime completion fails;
- `GitProposalManifestBuilder` accepts only `patch_program_job_id`, removing caller-supplied `patch_receipt` authority;
- manifest schema v2 binds the durable patch job identity, patch output checksum, exact proposed changes, persisted supervisor validation evidence, and proposal metadata;
- every changed Python postimage requires exact Ruff evidence and every changed Python test requires exact pytest evidence;
- proposal branches are restricted to valid `autonomy/proposal/*` refs without invoking Git or a shell.

The effective trust chain is:

`persisted governed job inputs → explicit durable mutation intent → role-scoped workspace capability → durable checksummed preimage journal → canonical assignment input checksum → exact program-job row → exact persisted execution-receipt identity → registered isolated patch executor → input/output-consistent isolated workspace mutation → durable lease completion or cross-process preimage recovery → manifest v2`.

## Current-main R3 reconstruction

PR #772 / branch `fix/brain-114m-r3-current-main` is the authoritative current-main trust root. It was reconciled onto canonical main `677a506ab61338e9d9a13ece67d972c2c22a044c` without overwriting the scientific BUILD-616R/617R3 surface. The branch is behind 0 and differs from main only in the intended 12 autonomy trust-root files.

Historical/current-parent branches #761, #762, #763, #765, #766, #767 and attempted #771 are not integration authorities. Downstream review, authorization, signature, plan, and mutation-execution branches must be reconstructed on the accepted #772 trust root after it merges.

## Failure-first classification

- Historical `steps=null`/pre-step GitHub-hosted-runner failures: **RUNNER/INFRASTRUCTURE**, not application-code evidence.
- First crash-recovery exact-head attempt: **CODE/STYLE** (`TRY004`), fixed without behavior change.
- Second exact-head attempt: **CODE/STYLE** (Ruff formatting drift), fixed without behavior change.
- No dependency, secret/credential, database, migration, deployment, or external-service failure was observed in the final #772 validation cycle.

## Validated state

**VALIDATED** — exact implementation head `54fa0d873b433e4a5749858809eecd7d8d691a80` passed all eight applicable workflows on 2026-08-09:

- BUILD-BRAIN-114M Git Proposal Manifest Validation — run `31326264882` — success;
- BUILD-BRAIN-108-113A Validation — run `31326264843` — success;
- BUILD-BRAIN-114A Validation — run `31326264853` — success;
- BUILD-BRAIN-114C Validation — run `31326264868` — success;
- BUILD-BRAIN-114I Safe Subset — run `31326264865` — success;
- CALYX-AGENT-003 Validation — run `31326264857` — success;
- BUILD-088E Validation — run `31326264860` — success, including PostgreSQL publication pipeline/readiness and BUILD-088B through BUILD-088D regressions;
- CALYX Workflow Governance Audit — run `31326264847` — success.

The dedicated BUILD-BRAIN-114M gate passed compilation, Ruff lint, Ruff formatting, focused proposal/rollback regressions, cross-process restart recovery, tampered-journal rejection, workspace-divergence fail-closed behavior, non-mutation/evidence-authority assertions, and diff hygiene.

## Review finding resolution

The P1 finding requiring recoverability before granting `workspace_write` is now addressed at both levels:

1. same-process lease/database completion failures restore exact preimages;
2. hard process/container loss between filesystem mutation and durable completion is recoverable by a new executor process from the durable isolated-workspace journal.

Reviewer-thread closure should cite the exact-head validation above. No merge should occur if a new unresolved material finding appears.

## Permanent non-authorities

BUILD-BRAIN-114M performs no Git command, branch creation, commit, push, pull-request creation, merge, deployment, scientific publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation. It stores no credentials and performs no network calls. Isolated workspace mutation is confined to the governed disposable workspace role and requires explicit durable mutation intent.

BUILD-BRAIN-114S—the first real branch/commit/push/open-PR executor—remains outside this implementation boundary and requires separate governance/transport activation. Merging #772 does not activate live Git/GitHub mutation.

## Remaining limitations

The journal is durable only to the isolated workspace filesystem. Loss of the entire disposable workspace/container volume requires deterministic workspace reconstruction rather than rollback from that lost journal. This is acceptable for the stated disposable-workspace boundary but is not equivalent to cross-host persistent storage. No claim of production Git mutation crash-atomicity is made.
