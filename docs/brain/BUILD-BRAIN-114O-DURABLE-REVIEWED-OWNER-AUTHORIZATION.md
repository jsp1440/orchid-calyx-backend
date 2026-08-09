# BUILD-BRAIN-114O — Durable reviewed owner authorization

## Status

Authoritative R2 reconstruction on strengthened BUILD-BRAIN-114P-R2 / PR #749. Draft and unmerged pending executable CI.

## Objective

Bind the exact persisted-patch and durable independent-review chain into a short-lived owner authorization request without giving the autonomous runtime signing secrets or Git/GitHub mutation authority.

## Current dependency chain

`#696 BUILD-BRAIN-114M-R1 → #747 BUILD-BRAIN-114N-R2 → #749 BUILD-BRAIN-114P-R2 → this BUILD-BRAIN-114O-R2`.

The strengthened trust chain is:

`canonical governed assignment inputs → exact persisted execution receipt → manifest v2 → durable independent reviews → owner-bound request v2`.

No layer may drop `patch_program_job_id`, substitute caller-supplied patch evidence, or bypass the canonical assignment-input checksum introduced by strengthened 114M-R1.

## Durable review chain

The gate consumes `DurableProposalAuthorizationStore`, not a caller-created review registry. For the exact manifest digest it reloads verified operational and security approvals, requires two distinct reviewers, revalidates manifest identity, and requires both review records to bind the same durable patch job.

Tampered rows, stale manifests, rejected reviews, reviewer conflicts, missing patch evidence, or mismatched patch identity fail closed.

## Request and owner-grant binding

114O accepts only `calyx-git-proposal-manifest-v2` and emits `calyx-git-mutation-authorization-request-v2`.

The request digest binds manifest digest, durable patch job ID, repository/base commit, proposal branch, postimage hashes, validation receipts, both durable review authorization digests, explicit future proposal actions, and an expiry no more than 30 minutes in the future.

The only action names represent a possible future proposal workflow: `create_branch`, `create_commit`, `push_branch`, and `open_pull_request`. This build performs none of them.

## R2 integration correction

The historical 114O test fixture persisted an execution receipt with the placeholder `input_checksum="input"`. Strengthened 114M-R1 correctly rejects such evidence because the persisted receipt must be bound to the canonical assignment inputs actually used by runtime execution.

R2 now computes the fixture receipt checksum with `canonical_checksum(assignment_inputs_for_program_job(program, claimed))`. This matches the runtime construction path and means the 114O regression suite exercises the strengthened persisted-input trust root rather than bypassing it.

## External owner verification boundary

`GitMutationAuthorizationGate` receives only an `OwnerGrantSignatureVerifier` capability. It contains no owner signing secret and no grant-minting API. A concrete public-key verifier belongs to BUILD-BRAIN-114Q.

## Permanent boundaries

No Git command, subprocess, branch creation, commit, push, pull-request creation, merge/auto-merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation is performed or authorized by this slice.

## Validation

Dedicated read-only CI compiles the strengthened persisted-patch, 114N-R2, 114P-R2, and 114O-R2 surfaces; runs Ruff and focused persistence/review/owner-grant regressions; asserts canonical assignment-input checksum usage; rejects placeholder receipt checksums; verifies manifest/request v2 and durable patch binding; and statically rejects mutation APIs.

Canonical CI incident #481 currently causes hosted jobs to terminate before workflow step 1 with `steps=null`. Such a run is infrastructure evidence only and is not a code pass or failure.

## Next dependency

BUILD-BRAIN-114Q may be reconstructed only on this exact R2 head and may provide a public-key-only verifier while preserving request v2, durable patch identity, durable review evidence, and the runtime no-signing-secret boundary. Actual Git/GitHub proposal execution remains a separate owner-governance decision.
