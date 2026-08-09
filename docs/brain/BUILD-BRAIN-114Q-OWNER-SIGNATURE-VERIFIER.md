# BUILD-BRAIN-114Q — External owner-signature verification boundary

## Objective

Provide a concrete public-key-only owner-grant verifier for BUILD-BRAIN-114O without placing owner signing authority inside the autonomous Calyx runtime.

## Current-parent reconstruction

This rebuild is stacked directly on current-parent BUILD-BRAIN-114O PR #724, preserving the hardened chain through #696 → #719 → #721 → #724. Historical 114Q ancestry is not trusted to carry forward parent files because stale copies previously risked restoring manifest/request v1 semantics.

The current chain preserves:

- `calyx-git-proposal-manifest-v2` only;
- `calyx-git-mutation-authorization-request-v2`;
- durable `patch_program_job_id` in the request digest;
- durable 114P review evidence for the exact manifest;
- distinct operational/security reviewers;
- verifier-only owner authorization with no signer or mutation executor.

## Trust model

`Ed25519OwnerGrantSignatureVerifier` accepts one or more Ed25519 public keys with explicit key IDs. It contains no private-key loader, signing method, approval method, grant-minting method, HMAC secret, or permissive fallback.

The owner's private key remains outside Calyx. Production key custody, signer location, recovery, rotation operator, and activation are separate governance/operations decisions.

## Signature contract

Signatures use:

`ed25519:<key_id>:<base64url-signature>`

The signature envelope is bounded printable ASCII and is preserved byte-for-byte by the owner-grant parser. It is deliberately not lowercased because both key IDs and base64url signatures are case-sensitive.

The signed bytes are domain-separated with `calyx-owner-grant-v1\0` followed by canonical UTF-8 JSON for the exact grant signing payload. The signed payload binds request digest, decision, owner principal, issued time, and expiry. The request digest already binds the manifest-v2 digest, patch program-job ID, repository/base commit, proposal branch, change hashes, validation receipts, durable review digests, action set, and expiry.

## Configuration and revocation

`CALYX_OWNER_VERIFY_KEYS_JSON` maps key IDs to unpadded base64url raw Ed25519 public keys. `CALYX_OWNER_REVOKED_KEY_IDS` optionally marks configured key IDs revoked.

Configuration fails closed for missing or malformed keys, invalid IDs, unknown revoked IDs, or an entirely revoked keyring. Rotation is additive-first: add replacement verification material, move the external signer, then revoke the old key after overlap.

## Validation

Focused tests cover exact Ed25519 verification, tampered payloads, wrong keys, malformed algorithms/signatures, rotation, revocation, missing configuration, valid 114O integration, revoked signer rejection, request binding to `patch_program_job_id`, case-sensitive envelope preservation, and absence of runtime signing APIs.

Dedicated read-only CI also statically requires manifest/request v2 and the durable patch identity. Canonical incident #481 currently prevents hosted jobs from reaching step 1, so no executable exact-head verdict is claimed until runner allocation resumes.

## Permanent boundaries

114Q verifies external owner signatures only. It creates no branch, commit, push, pull request, merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation.

The next bounded layer may construct a deterministic execution plan, but actual repository mutation remains a separate governance decision.
