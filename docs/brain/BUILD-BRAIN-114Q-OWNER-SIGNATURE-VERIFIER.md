# BUILD-BRAIN-114Q — External owner-signature verification boundary

## Status

Authoritative R2 reconstruction on BUILD-BRAIN-114O-R2 PR #753. Draft and unmerged pending executable CI.

## Objective

Provide a concrete public-key-only owner-grant verifier for BUILD-BRAIN-114O without placing owner signing authority inside the autonomous Calyx runtime.

## Authoritative dependency chain

`#696 BUILD-BRAIN-114M-R1 → #747 BUILD-BRAIN-114N-R2 → #749 BUILD-BRAIN-114P-R2 → #753 BUILD-BRAIN-114O-R2 → this BUILD-BRAIN-114Q-R2`.

This reconstruction is directly based on the exact #753 head, which preserves the fuller 114O regression suite and corrects its persisted execution fixture to derive `input_checksum` from `assignment_inputs_for_program_job(program, claimed)`. Thus 114Q inherits the strengthened 114M-R1 canonical assignment-input and exact patch input/output trust root.

The chain preserves `calyx-git-proposal-manifest-v2`, `calyx-git-mutation-authorization-request-v2`, durable `patch_program_job_id`, verified durable review evidence, distinct operational/security reviewers, and verifier-only owner authorization.

## Trust model

`Ed25519OwnerGrantSignatureVerifier` accepts one or more Ed25519 public keys with explicit key IDs. It contains no private-key loader, signing method, approval method, grant-minting method, HMAC secret, or permissive fallback.

The owner's private key remains outside Calyx. Production key custody, signer location, recovery, rotation operator, and activation are separate governance/operations decisions.

## Signature contract

Signatures are `ed25519:<key_id>:<base64url-signature>`. The envelope is bounded printable ASCII and preserved byte-for-byte; it is not lowercased because key IDs and base64url signatures are case-sensitive.

Signed bytes are domain-separated with `calyx-owner-grant-v1\0` followed by canonical UTF-8 JSON for the exact grant signing payload. The signed payload binds request digest, decision, owner principal, issued time, and expiry. The request digest already binds manifest-v2 digest, patch program-job ID, repository/base commit, proposal branch, change hashes, validation receipts, durable review digests, action set, and expiry.

## Configuration and revocation

`CALYX_OWNER_VERIFY_KEYS_JSON` maps key IDs to unpadded base64url raw Ed25519 public keys. `CALYX_OWNER_REVOKED_KEY_IDS` optionally marks configured key IDs revoked. Configuration fails closed for missing or malformed keys, invalid IDs, unknown revoked IDs, or an entirely revoked keyring.

## Validation

Focused tests cover exact Ed25519 verification, tampered payloads, wrong keys, malformed algorithms/signatures, rotation, revocation, missing configuration, valid owner-gate integration, revoked signer rejection, request binding to `patch_program_job_id`, case-sensitive envelope preservation, and absence of runtime signing APIs.

Dedicated read-only CI statically requires manifest/request v2 and durable patch identity. Canonical incident #481 currently causes private-repository hosted jobs to terminate before step 1 with `steps=null`; that is infrastructure evidence only, not a code verdict.

## Permanent boundaries

114Q verifies external owner signatures only. It creates no branch, commit, push, pull request, merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation.

BUILD-BRAIN-114R may construct a deterministic plan-only layer on this exact head. Actual repository mutation remains a separate owner-governance decision.
