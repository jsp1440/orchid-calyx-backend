# BUILD-BRAIN-114Q — External owner-signature verification boundary

## Status

R3 reconstruction directly on BUILD-BRAIN-114O-R3, rooted in the current-main 114M-R2 trust chain. Draft and unmerged pending executable CI.

## Objective

Provide a concrete public-key-only owner-grant verifier for BUILD-BRAIN-114O without placing owner signing authority inside the autonomous Calyx runtime.

## Current dependency chain

`#761 BUILD-BRAIN-114M-R2 → #762 BUILD-BRAIN-114N-R3 → #763 BUILD-BRAIN-114P-R3 → #765 BUILD-BRAIN-114O-R3 → this BUILD-BRAIN-114Q-R3`.

The chain preserves manifest v2, request v2, durable `patch_program_job_id`, canonical assignment-input checksum verification, exact patch input/output agreement, durable independent reviews, and verifier-only owner authorization.

## Trust model

`Ed25519OwnerGrantSignatureVerifier` accepts one or more Ed25519 public keys with explicit key IDs. It contains no private-key loader, signing method, approval method, grant-minting method, HMAC secret, or permissive fallback. The owner's private key remains outside Calyx; production key custody, recovery, rotation and activation are separate governance/operations decisions.

## Signature contract

Signatures are `ed25519:<key_id>:<base64url-signature>`. The bounded printable-ASCII envelope is preserved byte-for-byte; it is not lowercased because key IDs and base64url signatures are case-sensitive.

Signed bytes are domain-separated with `calyx-owner-grant-v1\0` followed by canonical UTF-8 JSON. The grant binds request digest, decision, owner principal, issued time and expiry. The request digest already binds manifest-v2 digest, patch program-job ID, repository/base commit, proposal branch, change hashes, validation receipts, durable review digests, action set and expiry.

## Configuration and revocation

`CALYX_OWNER_VERIFY_KEYS_JSON` maps key IDs to unpadded base64url raw Ed25519 public keys. `CALYX_OWNER_REVOKED_KEY_IDS` optionally marks configured key IDs revoked. Missing/malformed keys, invalid IDs, unknown revoked IDs, or an entirely revoked keyring fail closed.

## Validation

Focused tests cover exact Ed25519 verification, payload tampering, wrong keys, malformed signatures/algorithms, rotation, revocation, missing configuration, owner-gate integration, revoked signer rejection, patch-job request binding, case-sensitive envelope preservation, and absence of runtime signing APIs.

Dedicated read-only CI also requires manifest/request v2 and durable patch identity. Canonical incident #481 currently causes hosted jobs to terminate before step 1 with `steps=null`; this is infrastructure evidence only.

## Permanent boundaries

114Q verifies external owner signatures only. It creates no branch, commit, push, pull request, merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation.

## Next dependency

BUILD-BRAIN-114R may be rebuilt directly on this exact R3 head as a deterministic plan-only layer. Actual repository mutation remains a separate owner-governance decision.
