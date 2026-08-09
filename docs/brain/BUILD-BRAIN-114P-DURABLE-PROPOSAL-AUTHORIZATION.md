# BUILD-BRAIN-114P — Durable proposal-review authorization registry

## Objective

Close the persistence gap between BUILD-BRAIN-114N review evidence and any future repository-mutation executor. 114P introduces durable, tamper-evident review evidence before any real Git/GitHub mutation authority is considered.

## Current dependency chain

PR #694 is stacked on BUILD-BRAIN-114N #687, which is stacked on corrective BUILD-BRAIN-114M-R1 #696. This matters because all durable review evidence must now originate from `calyx-git-proposal-manifest-v2` and the exact persisted isolated-patch execution identified by `patch_program_job_id`.

## Persistence contract

`calyx_proposal_authorization_decisions` stores one immutable decision for each exact `(manifest_digest, review_class)` pair. The database enforces that pair as unique and also keeps `authorization_digest` unique. Review classes are restricted to `operational` and `security`.

The public write path is `DurableProposalAuthorizationStore.record_review()`. It does **not** accept a patch receipt or arbitrary `ProposalAuthorizationRecord`. Instead, the store constructs a 114N `ProposalAuthorizationBuilder` with `PersistedPatchExecutionService(db)`. The builder re-resolves the manifest's durable `patch_program_job_id`, verifies repository/branch/base-commit/output-checksum identity against persisted `CalyxProgramJob.evidence_json`, derives the producer from the authoritative isolated patch executor, then applies reviewer-role, evidence and self-approval governance before persistence.

This closes two confused-deputy paths: persistence cannot bless a caller-constructed authorization object, and it cannot bless a review built from caller-fabricated patch evidence.

The resulting `calyx-proposal-authorization-v2` payload includes `patch_program_job_id`; therefore the durable authorization digest cryptographically binds the exact patch execution. Pre-fix v1 review records cannot be decoded as v2.

The internal persistence operation is idempotent for an identical governed decision. If a competing writer wins the uniqueness race, the loser rolls back, reloads the winning row, verifies it, and returns it only if it is exactly the same decision. A different decision for the same manifest/review class fails closed as `PROPOSAL_AUTH_DURABLE_DECISION_ALREADY_RECORDED`.

## Read-time verification

Persistent rows are never trusted merely because they exist. Every read:

1. parses the stored JSON object;
2. verifies the current proposal-authorization schema;
3. recomputes the canonical SHA-256 authorization digest over the payload;
4. verifies it against the payload digest and dedicated row digest column;
5. verifies row manifest/review identity and allowed review class;
6. reconstructs `ProposalAuthorizationRecord`, including `patch_program_job_id`;
7. requires its canonical snapshot to match the stored payload exactly.

This detects malformed, stale-v1, drifted, or accidentally tampered persisted evidence. It is not claimed as protection against an attacker with unrestricted coherent database-write authority; database-write authority remains a separate trust boundary.

## Restart and dual-review behavior

`require()` reloads one exact digest-verified decision after process/session restart. `materialize_registry()` rebuilds the in-memory 114N registry only from verified persistent rows, preserving immutable-decision and independent dual-review semantics.

Focused tests now persist a real isolated-patch execution through `LeaseExecutionBridge` in the same SQLite database as the durable review rows. They cover restart/reload, idempotent replay, conflicting decision rejection, payload and row tamper detection, dual-review completion after reload, absence of arbitrary-record write APIs, self-approval rejection, and rejection of a manifest whose `patch_program_job_id` cannot be resolved.

## Migration

`migrations/20260808_calyx_proposal_authorization_decisions.sql` remains forward-only and uses `CREATE TABLE IF NOT EXISTS`. The `patch_program_job_id` is inside the canonical payload/digest rather than introduced as an independent mutable authority column in this slice. No production migration is applied by the PR.

## Permanent boundaries

114P persists review evidence only. It does not create branches, commits, pushes, pull requests, merge or auto-merge PRs, deploy software, publish scientific knowledge, activate taxonomy, perform production operator database mutation, or mutate the production Knowledge Graph.

## Validation

The dedicated read-only 114P workflow now compiles and Ruff-checks the persisted patch resolver plus the 114N/114P runtime and test surfaces, runs focused durable restart/idempotency/tamper/patch-identity/dual-review/self-approval regressions, asserts migration and non-mutation contracts, and performs diff hygiene.

Canonical repository CI incident #481 currently records hosted jobs terminating before workflow step 1 with `steps=null`; a zero-dependency one-echo diagnostic reproduced the same failure. Such attempts are infrastructure evidence only and do not count as executable validation. This slice must remain draft until #696/#687 and #694 exact-head workflows execute and pass.
