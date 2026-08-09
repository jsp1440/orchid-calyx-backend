# BUILD-BRAIN-114Q — Public-key owner signature verification

## Status

Authoritative R2 reconstruction on BUILD-BRAIN-114O-R2 / PR #750. Draft and unmerged pending executable CI.

## Objective

Provide a concrete public-key-only verifier for short-lived owner authorization grants without introducing a private signing key, grant-minting API, Git/GitHub mutation capability, merge authority, or deployment authority into Calyx runtime.

## Dependency chain

`#696 BUILD-BRAIN-114M-R1 → #747 114N-R2 → #749 114P-R2 → #750 114O-R2 → this 114Q-R2`.

The request remains `calyx-git-mutation-authorization-request-v2` and continues to bind the exact durable `patch_program_job_id`, manifest digest, independent review digests, repository/base commit, proposed branch, postimage hashes, validation receipts, actions, and short expiry.

## Verification contract

The verifier uses Ed25519 public keys only. Key identifiers are explicit and case-sensitive. Signature envelopes are `ed25519:<key_id>:<base64url-signature>` and are bounded before verification. Canonical grant bytes are domain separated with `calyx-owner-grant-v1\0` and deterministic JSON serialization.

Multiple public keys may coexist for rotation. Revocation is explicit and fail-closed. Unknown or malformed keys/signatures, tampered payloads, wrong algorithms, revoked keys, and invalid signatures fail verification.

The environment loader accepts public verification material through `CALYX_OWNER_VERIFY_KEYS_JSON` and optional revoked key IDs through `CALYX_OWNER_REVOKED_KEY_IDS`. No private key is loaded or represented by the runtime verifier.

## R2 inheritance

This reconstruction is stacked on 114O-R2, whose tests were corrected to use the canonical assignment input checksum required by strengthened 114M-R1. Therefore the public-key boundary no longer sits on the historical placeholder-receipt fixture chain.

## Permanent boundaries

No private signing key custody, signing API, grant minting, Git branch creation, commit, push, pull-request creation, merge/auto-merge, deployment, scientific publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation is authorized here.

## Validation

Dedicated CI compiles/lints the verifier and authorization gate, exercises exact Ed25519 verification, tamper rejection, wrong-key rejection, rotation/revocation, environment loading, case-sensitive envelopes, and integration with the owner authorization gate. Static assertions reject private-key and Git/GitHub mutation surfaces.

Canonical CI incident #481 may terminate hosted jobs before step 1 with `steps=null`; such a result is infrastructure evidence only.

## Next dependency

BUILD-BRAIN-114R may be reconstructed as a deterministic plan-only layer on this exact head. Any component that actually performs branch/commit/push/open-PR side effects remains a separate owner-governance decision and is not authorized by 114Q.
