# BUILD-BRAIN-114Q — Public-key owner signature verification

## Status

IMPLEMENTED and VALIDATED on the merged BUILD-BRAIN-114M → 114N → 114P → 114O trust chain. PR #784 was reconstructed directly on canonical `main` after its historical R5 branch was found to be 87 commits behind and rooted on a pre-repair 114O head. The reconstruction preserves merged 114O's trusted-clock and opaque-signature contract and adds only the five intended 114Q files.

## Objective

Provide concrete public-key-only Ed25519 owner-grant verification while preserving the hardened manifest-v2/request-v2/durable-review/patch-job provenance chain and granting no Git/GitHub mutation authority.

## Failure-first findings

- INTEGRATION/ANCESTRY — the original #784 base referenced a pre-repair 114O feature head. Resolved by rebuilding on merged canonical `main`; the shared `git_mutation_authorization.py` is no longer copied from stale ancestry.
- CRYPTO/REVOCATION P1 — owner-grant signing bytes did not bind the key ID. If identical public-key bytes were configured under a revoked ID and an active alias, a signature envelope could be relabeled to the active alias. Resolved without changing signing bytes by rejecting duplicate Ed25519 public-key material across different key IDs at keyring construction with `OWNER_SIGNATURE_DUPLICATE_KEY_MATERIAL`.
- DEPENDENCY CONTRACT — focused tests previously used the removed per-call `verify_grant(..., now=...)` API. Tests now use the merged 114O constructor-injected trusted clock and call `verify_grant()` without a caller-controlled timestamp.
- CI CONTRACT — the old workflow asserted a specific obsolete signature-parser implementation. It now asserts the merged 114O `_bounded_signature` and trusted-clock contract plus the 114Q duplicate-key-material defense.

## Verification contract

`Ed25519OwnerGrantSignatureVerifier` accepts only configured Ed25519 public keys. Keys use bounded explicit key IDs. Public-key bytes must be unique across the keyring, preventing revoked-key relabeling through aliases. Multiple distinct active public keys still permit controlled rotation overlap. Configured revocation fails closed.

Owner-grant signing bytes remain domain-separated and canonical. The signature envelope is `ed25519:<key_id>:<base64url-signature>` and remains case-sensitive. The merged 114O authorization parser treats signature text as an opaque bounded value and the concrete 114Q verifier owns algorithm-specific parsing.

Runtime configuration exposes only `CALYX_OWNER_VERIFY_KEYS_JSON` and `CALYX_OWNER_REVOKED_KEY_IDS`. No private-key loader, signing secret, signer, grant-minting method, or approval API exists in the production verifier surface. Private-key use appears only in focused tests.

## Validation

Exact implementation head `cded28613bdba293ba2a6b1315efac6e55df389b` passed all applicable workflows:

- BUILD-BRAIN-114Q Owner Signature Verifier Validation `31328400631` — success; compile, Ruff lint/format, Ed25519 + 114O regressions, duplicate-key alias rejection, public-key-only/v2 provenance assertions, and diff hygiene.
- Python Runtime Contract `31328400630` — success.
- CALYX Workflow Governance Audit `31328400638` — success.
- CALYX-AGENT-003 Validation `31328400641` — success.
- BUILD-088E Validation `31328400620` — success.

This Brain-only commit must receive its own exact-head validation before merge.

## Permanent boundaries

This build verifies owner grants only. It performs and grants no Git command, branch creation, commit, push, pull-request creation, merge/auto-merge, deployment, scientific publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation. Private-key custody and any live transport activation remain separate governance decisions.

## Next dependency

After this documentation head validates and PR #784 merges, BUILD-BRAIN-114R may be rebuilt directly on merged 114Q as a deterministic plan-only layer. 114R already has two known review blockers that must be fixed before any downstream 114S consideration: the owner-authorized base branch/ref is absent from the PR-open evidence chain, and nested operation parameters are only shallow-copied rather than recursively immutable/deep-copied.
