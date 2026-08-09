# BUILD-BRAIN-114R — Authorization-bound Git proposal execution plan

## Status

Authoritative R2 reconstruction on BUILD-BRAIN-114Q-R2. Draft and unmerged pending executable CI.

## Objective

Compile the exact persisted, independently reviewed, externally owner-approved proposal evidence chain into a deterministic Git/GitHub **plan**, while performing no repository mutation.

114R is the final evidence/planning layer before any future branch/commit/push/pull-request executor and intentionally stops at that governance boundary.

## Authoritative dependency chain

`#696 BUILD-BRAIN-114M-R1 → #747 BUILD-BRAIN-114N-R2 → #749 BUILD-BRAIN-114P-R2 → #753 BUILD-BRAIN-114O-R2 → BUILD-BRAIN-114Q-R2 → this BUILD-BRAIN-114R-R2`.

The chain preserves canonical governed assignment inputs, exact persisted patch execution, manifest v2, durable independent reviews, owner request v2, public-key-only Ed25519 verification, and the same durable `patch_program_job_id` through planning.

## R2 integration correction

The historical 114R test fixture used a synthetic fixed execution-receipt input checksum (`"1" * 64`). Strengthened 114M-R1 correctly rejects evidence that is not bound to the canonical runtime assignment inputs. R2 now computes the receipt checksum with `canonical_checksum(assignment_inputs_for_program_job(program, claimed))`, matching the authoritative execution path used by 114M-R1, 114P-R2, and 114O-R2.

## Input trust chain

At plan time `GitProposalExecutionPlanner.build()` rebuilds the authorization request from the exact manifest and current durable review store, compares it exactly to the supplied request, rechecks manifest digest and durable patch-job identity, verifies repository/base commit, proposal branch, postimage hashes, validation receipts, review digests, action set and expiry, re-verifies the external Ed25519 owner grant, and only then emits the plan.

Missing, rejected, conflicted, tampered, stale, or changed evidence fails closed.

## Deterministic plan v2

`calyx-git-proposal-execution-plan-v2` binds the manifest and request digests, durable patch job ID, repository/base commit, proposal branch, postimage hashes, validation and review digests, owner principal, expiry, verified signature-envelope digest, commit/PR metadata, and planned operations.

The `create_commit` operation carries `patch_program_job_id`. Operations use canonical dependency order: `create_branch`, `create_commit`, `push_branch`, `open_pull_request`. Only dependency-closed prefixes are accepted.

## Non-authority assertions

Every snapshot records `plan_only=true`. No branch, commit, push, or PR is created. Merge/auto-merge, deployment, publication, taxonomy activation, production database mutation, and production Knowledge Graph mutation remain unauthorized. The planner contains no subprocess, Git command, HTTP/GitHub mutation client, token, merge mechanism, deployment client, or publication client.

## Validation

Focused tests use durable in-memory Calyx program-job persistence, canonical assignment-input checksum construction, durable reviews, request-v2 generation, external Ed25519 verification, and deterministic plan compilation. Regressions cover patch-job binding, request mismatch, action prerequisites, manifest tampering, invalid signatures, expiry, and non-mutation state.

Dedicated read-only CI requires plan schema v2, durable patch identity, prerequisite checks, and absence of mutation implementation markers. Canonical incident #481 may terminate private-repository hosted jobs before step 1 with `steps=null`; that is infrastructure evidence only, not an executable code verdict.

## Governance boundary

The next step would execute real branch/commit/push/open-PR side effects. That is deliberately outside 114R and requires a separate owner decision. Merge/auto-merge, deployment, publication, taxonomy activation, and production scientific-data mutation remain separate authorities even if proposal execution is later enabled.
