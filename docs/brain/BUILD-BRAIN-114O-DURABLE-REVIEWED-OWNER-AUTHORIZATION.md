# BUILD-BRAIN-114O — Durable reviewed owner authorization

## Objective

Bind the exact hardened persisted-patch and durable independent-review chain into a short-lived owner authorization request without giving the autonomous runtime signing secrets or Git/GitHub mutation authority.

## Current dependency chain

This R2 rebuild is stacked on BUILD-BRAIN-114P-R2 PR #749, which is stacked on BUILD-BRAIN-114N-R2 PR #747, which is stacked on corrective BUILD-BRAIN-114M-R1 PR #696.

The evidence chain is:

`canonical assignment inputs → persisted governed patch execution → manifest v2 → durable independent reviews → owner-bound request v2`.

No layer may drop `patch_program_job_id`, weaken the canonical input checksum, or substitute caller-supplied patch evidence.

## Durable review chain

The gate accepts `DurableProposalAuthorizationStore`, not an in-memory caller registry. For the exact manifest digest, it reloads verified operational and security approvals, requires two distinct reviewers, revalidates the manifest identity, and requires both review records to bind the same durable patch job as the manifest.

Tampered durable rows, stale manifests, rejected reviews, reviewer conflicts, missing patch evidence, or mismatched patch identities fail closed.

## Request and owner-grant binding

114O accepts only `calyx-git-proposal-manifest-v2` and emits `calyx-git-mutation-authorization-request-v2`.

The request digest binds the manifest digest, durable patch job ID, repository/base commit, proposal branch, postimage hashes, validation receipts, both durable review authorization digests, explicit future proposal actions, and an expiry no more than 30 minutes in the future.

The only future proposal action names are `create_branch`, `create_commit`, `push_branch`, and `open_pull_request`. This build performs none of those actions.

The strengthened R2 regression fixture persists the isolated-patch receipt with `input_checksum=canonical_checksum(assignment_inputs_for_program_job(program, claimed))`, matching the exact runtime assignment object introduced by BUILD-BRAIN-114M-R1. Placeholder input checksums are no longer accepted by the root provenance resolver.

## External owner verification boundary

`GitMutationAuthorizationGate` receives only an `OwnerGrantSignatureVerifier` capability. It contains no owner signing secret and no grant-minting API. A concrete public-key verifier belongs to the downstream BUILD-BRAIN-114Q layer; 114O establishes only the verifier boundary and owner/request/expiry semantics.

## Permanent boundaries

No Git command, subprocess, branch creation, commit, push, pull-request creation, merge/auto-merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation is performed or authorized by this slice.

## Validation

Dedicated read-only CI compiles the persisted-patch, 114N, 114P, and 114O surfaces; Ruff-checks the changed owner-gate and durable-store paths; runs focused persistence/review/patch-identity/owner-grant regressions; verifies manifest/request v2 and durable patch binding; requires the canonical assignment-input fixture; and statically rejects signing secrets and mutation APIs.

Canonical CI incident #481 currently causes hosted jobs to terminate before step 1 with `steps=null`, so no exact-head executable verdict is claimed until runner allocation resumes.

## Next dependency

BUILD-BRAIN-114Q may provide a public-key-only verifier while preserving request v2, durable patch identity, durable review evidence, and the runtime no-signing-secret boundary. Actual Git proposal execution remains a separate governance decision.
