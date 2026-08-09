# BUILD-BRAIN-114O — Durable reviewed owner authorization

## Status

VALIDATED on canonical `main` after BUILD-BRAIN-114M-R3, 114N, and 114P merged. PR #783 was reconstructed onto merged 114P, retargeted to `main`, and reduced to the four intended additive 114O files.

## Objective

Bind the exact hardened persisted-patch and durable independent-review chain into a short-lived owner authorization request without giving the autonomous runtime signing secrets or Git/GitHub mutation authority.

## Current dependency chain

`#772 BUILD-BRAIN-114M-R3 → #781 BUILD-BRAIN-114N → #782 BUILD-BRAIN-114P → #783 BUILD-BRAIN-114O`.

Historical 114O branches rooted in superseded parents are source material only. The current branch has canonical main as its merge base and is behind 0.

The evidence chain is `canonical assignment inputs → explicit durable mutation intent + role-scoped workspace capability → persisted governed patch execution → manifest v2 → durable independent reviews → owner-bound request v2`. No layer may drop `patch_program_job_id`, weaken canonical input checksum identity, substitute caller-supplied patch evidence, or treat review evidence as execution authority.

## Durable review chain

The gate accepts `DurableProposalAuthorizationStore`, not a caller-created review registry. For the exact manifest digest it reloads verified operational and security approvals, requires distinct reviewers, revalidates manifest identity, and requires both review records to bind the same durable patch job. Tampered rows, stale manifests, rejected reviews, reviewer conflicts, missing patch evidence, or mismatched patch identities fail closed.

## Request and owner-grant binding

114O accepts only `calyx-git-proposal-manifest-v2` and emits `calyx-git-mutation-authorization-request-v2`. The request digest binds manifest digest, durable patch job ID, repository/base commit, proposal branch, postimage hashes, validation receipts, both durable review authorization digests, explicit future proposal actions, and an expiry no more than 30 minutes ahead.

The only future action names are `create_branch`, `create_commit`, `push_branch`, and `open_pull_request`; this build performs none of them. Merge is not allowlisted.

## Failure-first hardening

INTEGRATION/ANCESTRY — #783 originally depended on an obsolete pre-merge 114P head. It was reconstructed onto merged 114P and retargeted to canonical main with exactly four additive 114O files.

P1 CODE/AUTHORIZATION — Review found that `verify_grant(..., now=...)` let a runtime caller supply a historical timestamp and potentially revive an expired owner grant. Grant verification now uses a constructor-injected trusted clock; `verify_grant` exposes no per-call time override. The default clock is current UTC and test clocks are injected only at gate construction.

P2 CODE/CRYPTO CONTRACT — Review found that the generic grant parser incorrectly lowercased and required signatures to be 64-character lowercase hex before the injected verifier saw them. Signatures are now treated as bounded opaque case-sensitive text and are passed unchanged to the external verifier. Algorithm-specific shape and cryptographic validity belong to the verifier layer.

DEPENDENCY/TEST CONTRACT — The inherited 114O fixture used the superseded validation-target field. It now uses the merged 114N canonical `targets` contract covering the exact postimage.

STYLE — The first repaired exact-head run compiled and passed Ruff lint but stopped at one Ruff formatter transformation in the bounded-signature guard. That style-only defect was corrected without changing behavior.

## External owner verification boundary

`GitMutationAuthorizationGate` receives only an `OwnerGrantSignatureVerifier` capability. It contains no owner signing secret and no grant-minting API. The focused suite proves a mixed-case/non-hex signature envelope reaches the injected verifier unchanged. A concrete public-key-only verifier belongs to downstream BUILD-BRAIN-114Q.

## Validation

Exact implementation head `d2b283b3ed29a6c327af5a5d9f687c97b72595d3` passed all applicable workflows:

- BUILD-BRAIN-114O Durable Reviewed Owner Authorization Validation `31327440612` — success; compile, Ruff lint/format, focused durable review and grant regressions, verifier-only durable patch identity/non-mutation assertions, and diff hygiene all passed.
- CALYX-AGENT-003 Validation `31327440409` — success.
- BUILD-088E Validation `31327440416` — success.
- CALYX Workflow Governance Audit `31327440440` — success.

Focused regressions prove expired grants remain expired under the trusted clock, callers cannot pass a `now` override to verification, signature encoding is preserved exactly for the external verifier, merge remains outside the allowlist, and the runtime contains no owner signing secret or minting API.

## Permanent boundaries

No Git command, subprocess, branch creation, commit, push, pull-request creation, merge/auto-merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation is performed or activated by this slice. This layer verifies owner authorization evidence only; actual live Git/GitHub transport remains a separate governance boundary.

## Next dependency

BUILD-BRAIN-114Q may be reconstructed only after this exact documentation head revalidates and #783 is merged. Actual Git/GitHub proposal execution remains a separate explicit governance decision.
