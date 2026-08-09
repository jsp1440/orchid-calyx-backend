# BUILD-BRAIN-114O — Durable reviewed owner authorization

## Status

R5 reconstruction directly on BUILD-BRAIN-114P-R5 PR #782 exact validated head `524581deff6e60f6d26dac54813f850d31fd82b9`. Draft and unmerged. Parent exact-head BUILD-BRAIN-114P, CALYX-AGENT-003, and Workflow Governance validation are green.

## Objective

Bind the exact hardened persisted-patch and durable independent-review chain into a short-lived owner authorization request without giving the autonomous runtime signing secrets or Git/GitHub mutation authority.

## Current dependency chain

`#772 BUILD-BRAIN-114M-R3 → #781 BUILD-BRAIN-114N-R6 → #782 BUILD-BRAIN-114P-R5 → #783 BUILD-BRAIN-114O-R5`.

Historical #775 / R4 is rooted in superseded #773 ancestry and is source material only. R5 reapplies only the four additive 114O files directly on the exact validated #782 head.

The evidence chain is `canonical assignment inputs → explicit durable mutation intent + role-scoped workspace capability → persisted governed patch execution → manifest v2 → durable independent reviews → owner-bound request v2`. No layer may drop `patch_program_job_id`, weaken the canonical input checksum, substitute caller-supplied patch evidence, or treat review evidence as execution authority.

## Durable review chain

The gate accepts `DurableProposalAuthorizationStore`, not a caller-created review registry. For the exact manifest digest it reloads verified operational and security approvals, requires distinct reviewers, revalidates manifest identity, and requires both review records to bind the same durable patch job. Tampered rows, stale manifests, rejected reviews, reviewer conflicts, missing patch evidence, or mismatched patch identities fail closed.

## Request and owner-grant binding

114O accepts only `calyx-git-proposal-manifest-v2` and emits `calyx-git-mutation-authorization-request-v2`. The request digest binds manifest digest, durable patch job ID, repository/base commit, proposal branch, postimage hashes, validation receipts, both durable review authorization digests, explicit future proposal actions, and an expiry no more than 30 minutes ahead.

The only future action names are `create_branch`, `create_commit`, `push_branch`, and `open_pull_request`; this build performs none of them. Merge is not allowlisted.

The R5 regression fixture persists the isolated-patch receipt with `canonical_checksum(assignment_inputs_for_program_job(program, claimed))`, matching the authoritative current 114M-R3 input object. Placeholder input checksums cannot satisfy the root provenance resolver.

## External owner verification boundary

`GitMutationAuthorizationGate` receives only an `OwnerGrantSignatureVerifier` capability. It contains no owner signing secret and no grant-minting API. The test-local HMAC verifier exists only to prove the capability boundary; a concrete public-key-only verifier belongs to downstream BUILD-BRAIN-114Q.

## Permanent boundaries

No Git command, subprocess, branch creation, commit, push, pull-request creation, merge/auto-merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation is performed or authorized by this slice.

## Validation

Dedicated read-only CI compiles the current persisted-patch, 114N-R6, 114P-R5 and 114O-R5 surfaces, runs focused persistence/review/patch-identity/owner-grant regressions, requires the canonical assignment-input fixture, and statically rejects signing secrets and mutation APIs.

Initial exact head `aa838874c4007b8885d3eae2ae4eafe9c73fbb56` executed normally and exposed one style-only blocker: Ruff formatter drift in the focused owner-authorization test. No Ruff rule violation or compile failure occurred. The three exact formatter changes were applied without changing behavior.

Exact implementation head `6c61a4f9f5e735cf340458efc57482976e1c374c` then passed BUILD-BRAIN-114O run `31296689932` end to end: dependency installation, compile, Ruff lint/format, focused durable reviewed authorization regressions, verifier-only durable patch identity/non-mutation assertions, and diff hygiene. The same exact head passed CALYX-AGENT-003 run `31296689939` and Workflow Governance run `31296689978`.

This documentation-only commit records that receipt and becomes the new R5 head. It must receive its own executable exact-head validation before serving as the authoritative parent for 114Q.

## Next dependency

BUILD-BRAIN-114Q must be rebuilt directly on this exact validated R5 head before plan-only 114R can again be authoritative. Actual Git/GitHub proposal execution remains a separate owner-governance decision.
