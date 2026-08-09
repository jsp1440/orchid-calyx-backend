# BUILD-BRAIN-114Q — External owner-signature verification boundary

## Objective

Provide a concrete owner-grant verification implementation for BUILD-BRAIN-114O without placing owner signing authority inside the autonomous Calyx runtime.

## Current-parent reconstruction

The original 114Q branch was created before the 114M-R1/114N/114P/114O provenance hardening. When the parent advanced, the old 114Q copy of `git_mutation_authorization.py` still carried `calyx-git-proposal-manifest-v1` / request-v1 semantics and conflicted with the hardened parent. Replaying that file wholesale would have silently removed `patch_program_job_id` from the owner authorization request.

This replacement is rebuilt directly on the latest durable 114O parent and preserves:

- `calyx-git-proposal-manifest-v2` only;
- `calyx-git-mutation-authorization-request-v2`;
- the durable `patch_program_job_id` in the request digest;
- durable 114P review evidence for the exact manifest;
- distinct operational/security reviewers;
- verifier-only owner authorization with no signer or mutation executor.

Only the signature-envelope/public-key changes are layered on top. This prevents ancestry drift from weakening the persisted patch-provenance chain.

## Trust model

The Calyx application receives **public verification material only**. `Ed25519OwnerGrantSignatureVerifier` accepts one or more Ed25519 public keys identified by explicit key IDs. It exposes only verification plus active/revoked key metadata. It contains no private-key loader, signing method, approval method, grant minting method, shared HMAC secret, or fallback verifier.

A compromise of the Calyx application process can read the configured public keys but those keys cannot produce a valid owner signature. The owner's Ed25519 private key must remain in a separately controlled signer, hardware-backed key service, offline operator device, or equivalent boundary outside the Calyx worker and repository-execution sandbox.

This implementation does **not** choose or activate a production owner key. Key custody and production activation remain an operations/governance decision.

## Signature contract

Signatures use the envelope:

`ed25519:<key_id>:<base64url-signature>`

Signature envelopes are bounded printable ASCII and are preserved byte-for-byte by the 114O grant parser. They are deliberately **not lowercased**, because Ed25519 base64url signatures and key IDs are case-sensitive.

The external signer signs the exact bytes returned by `owner_grant_signing_bytes(payload)`. Those bytes are:

1. the domain separator `calyx-owner-grant-v1\0`;
2. followed by UTF-8 JSON for the exact 114O grant signing payload with sorted keys, compact separators, Unicode preserved, and non-finite numbers prohibited.

The signed payload binds the 114O request digest, decision, approved owner principal, issued-at time, and expiry. The request digest itself binds the manifest-v2 digest, durable patch program-job ID, repository/base commit, proposal branch, change hashes, validation receipt digests, durable review authorization digests, action set, and expiry.

## Configuration

`CALYX_OWNER_VERIFY_KEYS_JSON` contains a JSON object mapping key IDs to raw 32-byte Ed25519 public keys encoded as unpadded base64url.

`CALYX_OWNER_REVOKED_KEY_IDS` is an optional comma-separated set of configured key IDs that must fail verification.

Startup/configuration fails closed when:

- no keyring is configured;
- key JSON or public-key encoding is malformed;
- a key ID is invalid;
- a revoked key ID is not present in the configured keyring; or
- every configured key is revoked.

There is intentionally no implicit development key and no permissive verifier.

## Rotation and revocation

Rotation is additive first: publish the replacement public key alongside the old key, move the external signer to the replacement key ID, then revoke the old key ID after the intended overlap window. A revoked key cannot verify even if its public material remains configured. Unknown signer IDs fail closed.

Public-key configuration is not itself an authorization to mutate repositories. It only establishes which external signatures 114O may recognize.

## Validation

Focused tests cover exact Ed25519 verification, tampered payload rejection, wrong signer/key rejection, malformed/wrong-algorithm signatures, rotation/revocation, missing configuration, valid 114O integration, revoked signer rejection, request-digest binding to `patch_program_job_id`, case-sensitive signature preservation, and absence of signing methods/material on the runtime verifier surface.

Dedicated CI also statically requires request/manifest v2 and `patch_program_job_id`, preventing a future stale-parent replay from silently restoring the v1 authorization contract.

Test private keys are generated only inside the focused test module. Runtime code imports only `Ed25519PublicKey`.

## Permanent boundaries

114Q implements verification only. It does not create branches, commits, pushes, pull requests, merges, deployments, publications, taxonomy activations, production database mutations, or production Knowledge Graph mutations.

A bounded branch/commit/push/PR executor remains a separate governance milestone. Selecting the real owner key, signer location, recovery process, rotation operator, and deployment configuration is also a governance/operations decision.

Canonical hosted CI incident #481 remains unresolved; exact-head hosted validation is not considered executable when GitHub reports `steps=null` before workflow step 1.
