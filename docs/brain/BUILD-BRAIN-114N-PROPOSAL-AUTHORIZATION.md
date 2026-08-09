# BUILD-BRAIN-114N — Governed proposal authorization record

## Objective

Add immutable repository-proposal review evidence after BUILD-BRAIN-114M without granting Calyx Git or GitHub mutation authority.

## Current lineage

This rebuild is based directly on strengthened BUILD-BRAIN-114M-R1 head `0571ceb6de79faf569f6acc0b0e05383547b5cd5`, after the parent added runtime role-scoping and end-to-end persisted isolated-patch verification. Historical 114N PR #719 is no longer authoritative because it was built on an earlier 114M-R1 head and became non-mergeable. This branch carries only the 114N review-evidence layer on top of the exact strengthened parent.

## Hardened trust chain

114N accepts only `calyx-git-proposal-manifest-v2`. The manifest binds an exact durable `patch_program_job_id` plus repository, source autonomy branch, base commit, patch output checksum, proposed branch, change hashes, validation evidence, and manifest digest.

`ProposalAuthorizationBuilder` does not accept a caller-supplied patch receipt. Before creating review evidence it resolves the exact patch job through `PersistedPatchExecutionService`, backed by durable `CalyxProgramJob.evidence_json`. The strengthened parent additionally verifies durable assignment/program/job identity, canonical assignment input checksum, and exact governed patch inputs against persisted output changes. 114N therefore inherits those checks before any review evidence can be produced.

Each authorization record binds `patch_program_job_id` into its immutable payload and digest. Manifest v1 is rejected rather than silently grandfathered.

## Review governance

Reviewers must be distinct from requester and persisted patch producer, role-qualified for `security` or `operational`, and provide rationale, evidence URIs, and timezone-aware decision time.

`ProposalAuthorizationRegistry` keys decisions by `(manifest_digest, review_class)`. Identical replay is idempotent; conflicting replacement is rejected.

`proposal_review_status()` requires both review classes and two distinct reviewer identities. Rejection blocks completion; missing classes remain pending; same-reviewer dual approval is explicitly rejected as a reviewer conflict.

Even complete review evidence grants no Git mutation, commit, push, pull-request creation, automatic merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation authority.

## Validation contract

Dedicated CI compiles and lints the strengthened persisted-patch resolver together with both review surfaces and both focused test files. Focused regressions cover deterministic non-authority records, manifest tampering, persisted patch checksum/identity mismatch, missing durable patch-job identity, requester/producer self-approval, reviewer-role enforcement, stale manifests, immutable rejection, independent dual-review completion, reviewer conflict, and rejection behavior.

Static assertions require manifest v2, `PersistedPatchExecutionService`, bound `patch_program_job_id`, absence of a `patch_receipt` runtime path, and permanent non-authority flags.

## Current CI incident

Canonical issue #481 tracks GitHub-hosted jobs terminating before workflow step 1 with `steps=null`. Such runs do not provide compile, lint, pytest, or diff-hygiene evidence and must not be interpreted as code failures or passes.

This branch must remain draft/unmerged until BUILD-BRAIN-114M-R1 is executable-green and this exact unchanged 114N current-parent head executes and passes real workflow steps.

## Next dependency

BUILD-BRAIN-114P must be rebuilt or rebased only after this exact 114N layer is established, so durable review persistence inherits the strengthened 114M-R1 trust chain. Downstream 114O/114Q/114R must then follow in order. Actual Git/GitHub mutation remains a separate owner-governance boundary.
