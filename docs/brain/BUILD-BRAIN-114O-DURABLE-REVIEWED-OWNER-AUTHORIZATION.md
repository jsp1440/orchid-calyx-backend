# BUILD-BRAIN-114O — Durable reviewed owner authorization

## Status

R4 reconstruction directly on BUILD-BRAIN-114P-R4 PR #773, rooted in hardened BUILD-BRAIN-114M-R2 PR #761 through BUILD-BRAIN-114N-R4 PR #771. Draft and unmerged pending executable CI.

## Objective

Bind the exact hardened persisted-patch and durable independent-review chain into a short-lived owner authorization request without giving the autonomous runtime signing secrets or Git/GitHub mutation authority.

## Current dependency chain

`#761 BUILD-BRAIN-114M-R2 → #771 BUILD-BRAIN-114N-R4 → #773 BUILD-BRAIN-114P-R4 → this BUILD-BRAIN-114O-R4`.

The evidence chain is `canonical assignment inputs → explicit durable mutation intent + role-scoped workspace capability → persisted governed patch execution → manifest v2 → durable independent reviews → owner-bound request v2`. No layer may drop `patch_program_job_id`, weaken the canonical input checksum, substitute caller-supplied patch evidence, or treat review evidence as execution authority.

## Durable review chain

The gate accepts `DurableProposalAuthorizationStore`, not a caller-created review registry. For the exact manifest digest it reloads verified operational and security approvals, requires distinct reviewers, revalidates manifest identity, and requires both review records to bind the same durable patch job. Tampered rows, stale manifests, rejected reviews, reviewer conflicts, missing patch evidence, or mismatched patch identities fail closed.

## Request and owner-grant binding

114O accepts only `calyx-git-proposal-manifest-v2` and emits `calyx-git-mutation-authorization-request-v2`. The request digest binds manifest digest, durable patch job ID, repository/base commit, proposal branch, postimage hashes, validation receipts, both durable review authorization digests, explicit future proposal actions, and an expiry no more than 30 minutes ahead.

The only future action names are `create_branch`, `create_commit`, `push_branch`, and `open_pull_request`; this build performs none of them.

The R4 regression fixture persists the isolated-patch receipt with `canonical_checksum(assignment_inputs_for_program_job(program, claimed))`, matching the authoritative hardened 114M-R2 input object. Placeholder input checksums cannot satisfy the root provenance resolver.

## External owner verification boundary

`GitMutationAuthorizationGate` receives only an `OwnerGrantSignatureVerifier` capability. It contains no owner signing secret and no grant-minting API. A concrete public-key verifier belongs to downstream BUILD-BRAIN-114Q.

## Permanent boundaries

No Git command, subprocess, branch creation, commit, push, pull-request creation, merge/auto-merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation is performed or authorized by this slice.

## Validation

Dedicated read-only CI compiles the current persisted-patch, 114N-R4, 114P-R4 and 114O-R4 surfaces, runs focused persistence/review/patch-identity/owner-grant regressions, requires the canonical assignment-input fixture, and statically rejects signing secrets and mutation APIs.

Canonical incident #481 currently causes hosted jobs to terminate before workflow step 1 with `steps=null`; such a result is infrastructure evidence only.

## Next dependency

BUILD-BRAIN-114Q must be rebuilt directly on this exact R4 head before plan-only 114R can again be authoritative. Actual Git/GitHub proposal execution remains a separate owner-governance decision.
