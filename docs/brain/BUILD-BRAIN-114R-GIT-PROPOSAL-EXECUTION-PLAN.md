# BUILD-BRAIN-114R — Authorization-bound Git proposal execution plan

## Objective

Compile the exact reviewed and owner-approved proposal evidence chain into a deterministic Git/GitHub **plan**, while still performing no repository mutation.

114R is the final evidence/planning layer before any future branch/commit/push/pull-request executor. It intentionally stops at that governance boundary.

## Current-parent reconstruction

The original 114R branch inherited the pre-hardening 114Q ancestry. After retargeting, its focused tests still constructed `calyx-git-proposal-manifest-v1` and caller-supplied patch receipts, so they no longer exercised the durable patch-provenance chain. This replacement is rebuilt directly on current-parent 114Q PR #717 and uses only manifest/request v2 plus durable 114P review evidence.

## Input trust chain

At plan time `GitProposalExecutionPlanner.build()`:

1. rebuilds the 114O authorization request from the exact manifest and current durable 114P review store;
2. compares the rebuilt request snapshot to the supplied request exactly;
3. therefore rechecks the manifest digest, durable `patch_program_job_id`, repository/base commit, proposal branch, postimage hashes, validation receipt digests, durable review authorization digests, allowlisted actions, and expiry;
4. asks the configured 114O gate to verify the supplied owner grant again through the 114Q public-key signature verifier; and
5. only then emits a plan.

If durable review evidence is missing, rejected, conflicted, tampered, or changed since authorization, request reconstruction fails closed. If the owner signature is invalid/revoked or the grant has expired, no plan is produced.

## Deterministic plan v2

The plan directly binds and exposes:

- exact manifest digest;
- exact durable `patch_program_job_id`;
- exact 114O request digest;
- repository and base commit;
- `autonomy/proposal/*` branch;
- changed-file postimage SHA-256 values;
- validation receipt digests;
- durable security/operational authorization digests;
- owner principal and grant expiry;
- a SHA-256 digest of the exact verified signature envelope;
- commit title, PR title, and summary from the exact manifest; and
- the authorized action set.

The `create_commit` operation also carries `patch_program_job_id`, so an eventual separately governed executor would not have to infer which durable patch execution supplies the authorized postimages.

Operations are emitted in canonical dependency order regardless of authorization-request action ordering: `create_branch`, `create_commit`, `push_branch`, `open_pull_request`. Only authorized actions appear; planning never broadens authority.

## Non-authority assertions

Every plan snapshot records `plan_only=true` and keeps all side-effect/activation authorities false: no branch, commit, push, or pull request has been created; merge/auto-merge, deployment, publication, taxonomy activation, production database mutation, and production Knowledge Graph mutation remain unauthorized.

The planner contains no subprocess, Git command, HTTP mutation client, GitHub API client, credential, token, merge mechanism, deployment client, or publication client.

## Validation contract

Focused tests use the real SQLite Calyx program-job tables and `LeaseExecutionBridge` to persist an authoritative isolated-patch execution, record both durable 114P reviews through governed builders, produce a v2 owner request, verify an external Ed25519 owner signature, and compile the plan. Regressions cover deterministic planning, direct `patch_program_job_id` binding, request/patch-job mismatch, canonical action subsets/order, manifest tampering, invalid signature, expiry, and non-mutation assertions.

Dedicated CI statically requires plan schema v2 and `patch_program_job_id`, and forbids repository/network mutation implementation markers.

Canonical CI incident #481 remains active: a hosted run that terminates with `steps=null` before step 1 is infrastructure evidence, not an executable code verdict.

## Governance boundary

The next architectural step would be an executor that actually creates a branch, creates a commit, pushes a branch, and opens a pull request from this plan. **That step crosses from evidence generation into real external side effects and remains a separate governance decision.**

114R does not authorize merge or auto-merge under any circumstances, and it does not authorize deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation.
