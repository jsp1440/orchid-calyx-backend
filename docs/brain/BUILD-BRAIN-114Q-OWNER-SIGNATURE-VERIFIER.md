# BUILD-BRAIN-114Q — Public-key owner signature verification

## Status

R5 reconstruction directly on BUILD-BRAIN-114O-R5 PR #783 exact validated head `7a17565bc92f94537cfd461967c87e9fdd8cba8d`. Draft and unmerged. Parent exact-head BUILD-BRAIN-114O, CALYX-AGENT-003, and Workflow Governance validation are green.

## Objective

Replace the test-only owner grant verification capability with a concrete public-key-only Ed25519 verifier while preserving the hardened manifest-v2/request-v2/durable-review/patch-job provenance chain and granting no Git/GitHub mutation authority.

## Current dependency chain

`#772 BUILD-BRAIN-114M-R3 → #781 BUILD-BRAIN-114N-R6 → #782 BUILD-BRAIN-114P-R5 → #783 BUILD-BRAIN-114O-R5 → this BUILD-BRAIN-114Q-R5`.

Historical #779 / R4 is source material only because it is rooted in superseded #775 ancestry. R5 reapplies only the six intended public-key verification files directly on the exact validated #783 head.

## Verification contract

`Ed25519OwnerGrantSignatureVerifier` accepts only configured Ed25519 public keys. Keys are identified by bounded explicit key IDs. Multiple active public keys permit controlled rotation overlap; configured revocation fails closed. Empty, malformed, unknown, revoked, or invalid signatures fail closed.

Owner-grant signing bytes are domain-separated and canonical. The signature envelope is `ed25519:<key_id>:<base64url-signature>` and remains case-sensitive. `GitMutationAuthorizationGrant.from_mapping()` therefore preserves the signature envelope exactly rather than lowercasing it or constraining it to SHA-256-shaped hex.

Runtime configuration exposes only `CALYX_OWNER_VERIFY_KEYS_JSON` and `CALYX_OWNER_REVOKED_KEY_IDS`. No private-key loader, secret, signer, grant minting method, or approval API exists in the production verifier surface. Private-key use appears only in focused tests to generate signatures that exercise verification.

## Permanent boundaries

This build verifies owner grants only. It performs and grants no Git command, branch creation, commit, push, pull-request creation, merge/auto-merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation.

## Validation

Dedicated read-only CI compiles and lints the verifier and current owner-authorization gate, runs focused Ed25519 and 114O regressions, verifies public-key-only configuration and v2 provenance, and checks diff hygiene. `cryptography>=44,<46` is added as the bounded dependency required for Ed25519 verification.

R5 must receive executable exact-head BUILD-BRAIN-114Q validation plus relevant broad regressions before plan-only 114R reconstruction. Failures are corrected before expansion.

## Next dependency

After exact-head validation, BUILD-BRAIN-114R may be rebuilt directly on this R5 head as a deterministic plan-only execution layer. Actual Git/GitHub side-effect execution remains outside this chain and requires an explicit owner governance decision.
