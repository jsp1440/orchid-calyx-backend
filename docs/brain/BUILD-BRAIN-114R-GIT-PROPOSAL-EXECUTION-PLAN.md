# BUILD-BRAIN-114R — Authorization-bound Git proposal execution plan

## Objective

Compile the exact persisted, independently reviewed, externally owner-approved proposal evidence chain into a deterministic Git/GitHub **plan**, while performing no repository mutation.

114R is the final evidence/planning layer before any future branch/commit/push/pull-request executor and intentionally stops at that governance boundary.

## Current-parent reconstruction

This rebuild is stacked directly on current-parent BUILD-BRAIN-114Q PR #726, preserving the exact hardened sequence #696 → #719 → #721 → #724 → #726. Historical 114R ancestry is superseded because its earlier parent chain no longer represented the newest persisted-patch provenance.

## Input trust chain

At plan time `GitProposalExecutionPlanner.build()`:

1. rebuilds the 114O request from the exact manifest and current durable 114P review store;
2. compares the rebuilt request to the supplied request exactly;
3. rechecks manifest digest, durable `patch_program_job_id`, repository/base commit, proposal branch, postimage hashes, validation receipts, review digests, action set, and expiry;
4. verifies the owner grant again through the 114Q Ed25519 public-key verifier; and
5. only then emits a deterministic plan.

Missing, rejected, conflicted, tampered, or changed durable evidence fails closed. Invalid/revoked/expired owner authorization produces no plan.

## Deterministic plan v2

`calyx-git-proposal-execution-plan-v2` binds the exact manifest and authorization request digests, durable patch job ID, repository/base commit, proposal branch, postimage hashes, validation and review digests, owner principal, expiry, exact verified signature-envelope digest, commit/PR metadata, and planned operations.

The `create_commit` operation carries `patch_program_job_id`, eliminating inference about which persisted patch execution supplies authorized postimages.

Operations use canonical dependency order: `create_branch`, `create_commit`, `push_branch`, `open_pull_request`. Only dependency-closed prefixes are accepted; sparse authorization that skips prerequisites fails closed.

## Non-authority assertions

Every snapshot records `plan_only=true`. No branch, commit, push, or PR is created. Merge/auto-merge, deployment, publication, taxonomy activation, production database mutation, and production Knowledge Graph mutation remain unauthorized.

The planner contains no subprocess, Git command, HTTP/GitHub mutation client, token, merge mechanism, deployment client, or publication client.

## Validation

Focused tests use real in-memory SQLite Calyx program-job persistence and `LeaseExecutionBridge`, governed durable reviews, request-v2 generation, external Ed25519 owner verification, and deterministic plan compilation. Regressions cover patch-job binding, request mismatch, action prerequisites, manifest tampering, invalid signatures, expiry, and non-mutation state.

Dedicated read-only CI requires plan schema v2, durable patch identity, prerequisite checks, and absence of mutation implementation markers. Canonical CI incident #481 remains active; `steps=null` before step 1 is infrastructure evidence rather than an executable code verdict.

## Governance boundary

The next step would execute real branch/commit/push/open-PR side effects. That is deliberately outside 114R and requires a separate governance decision. Merge/auto-merge, deployment, publication, taxonomy activation, and production scientific-data mutation remain separate authorities even if proposal execution is later enabled.
