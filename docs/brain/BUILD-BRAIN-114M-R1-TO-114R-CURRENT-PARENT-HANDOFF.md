# BUILD-BRAIN-114M-R1 → 114R strengthened handoff

## Authoritative chain

The autonomy proposal trust chain has been reconstructed again after BUILD-BRAIN-114M-R1 strengthened persisted-patch evidence with canonical assignment-input checksums, exact requested-patch/output agreement, and role-scoped mutation capability.

Current sequence:

1. **#696 — BUILD-BRAIN-114M-R1** — strengthened durable persisted-patch provenance and manifest v2 root.
2. **#747 — BUILD-BRAIN-114N-R2** — governed operational/security review evidence directly on the exact strengthened #696 head.
3. **#749 — BUILD-BRAIN-114P-R2** — durable tamper-evident review registry directly on #747; historical placeholder receipt checksum corrected.
4. **#753 — BUILD-BRAIN-114O-R2** — durable-reviewed owner authorization request v2 directly on #749; fuller regression surface and canonical assignment-input fixture.
5. **BUILD-BRAIN-114Q-R2** — public-key-only Ed25519 owner-grant verification directly on #753.
6. **BUILD-BRAIN-114R-R2** — deterministic authorization-bound execution plan v2 directly on the authoritative 114Q-R2 head.

Historical #719, #721, #724 and duplicate reconstruction paths are closed or superseded. Historical #726/#728 are no longer authoritative and should remain unmerged once their R2 replacements exist.

## Trust invariants

- canonical assignment inputs are cryptographically bound to persisted execution evidence;
- exact governed patch inputs must agree with persisted output paths/preimages/postimages/sizes;
- exact durable `patch_program_job_id` survives manifest, review records, owner request, and plan;
- caller-supplied patch receipts cannot establish proposal provenance;
- operational and security reviews are durable, exact-manifest-bound, approved, and from distinct reviewers;
- owner authorization is short-lived and exact-request-bound;
- Ed25519 verification uses public material only and preserves case-sensitive signature envelopes;
- 114R re-derives the request from current durable evidence and re-verifies the grant at plan time;
- operations are dependency-closed and canonical;
- no layer silently broadens authority.

## Permanent non-authorities through 114R

114R is **plan-only**. The chain does not execute branch creation, commit creation, push, pull-request creation, merge/auto-merge, deployment, scientific publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation.

Actual Git/GitHub proposal execution is the next governance boundary and requires an explicit owner decision. BUILD-BRAIN-114S/114T mutation-executor implementations are not an authorized integration lane.

## Validation state

Each R2 layer has focused tests and read-only CI. Canonical incident #481 remains the executable-validation blocker: private-repository hosted jobs terminate before workflow step 1 with `steps=null`, providing no compile, Ruff, pytest, or diff-hygiene verdict.

When runners resume, validate the unchanged chain in order beginning with #696, fix actual executable failures before advancing, and only then consider normal merge review. No production or merge authority is implied by a green test result.
