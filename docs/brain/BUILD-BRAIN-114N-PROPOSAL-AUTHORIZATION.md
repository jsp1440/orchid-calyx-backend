# BUILD-BRAIN-114N — Governed proposal authorization record

## Status

R4 reconstruction directly on BUILD-BRAIN-114M-R3 PR #772 / `fix/brain-114m-r3-current-main`. Draft and unmerged pending executable CI.

## Objective

Add immutable repository-proposal review evidence after BUILD-BRAIN-114M without granting Calyx Git or GitHub mutation authority.

## Current lineage

This branch starts from exact #772 head `15464466ebd3f463d4ab3351308e2e6b4cba81e5`, the current-main reconstruction of the hardened 114M trust root. #772 is exactly nine intended trust-root files ahead and zero behind the then-current `main`; its merge-base audit found no overlap between intervening current-main work and the 114M trust files.

The parent preserves canonical assignment-input construction, role-scoped `workspace_write`, durable receipt identity, canonical input-checksum recomputation, exact governed patch input/output agreement, persisted external-sandbox evidence, and manifest v2 bound to `patch_program_job_id`.

Historical #761/#762 and downstream stacks rooted in the superseded R2 ancestry are no longer authoritative.

## Hardened trust chain

114N accepts only `calyx-git-proposal-manifest-v2`. `ProposalAuthorizationBuilder` does not accept caller-supplied patch receipts. Before creating review evidence it resolves the exact durable patch job through `PersistedPatchExecutionService`; the #772 parent verifies assignment/program/job identity, canonical assignment inputs, persisted execution checksum, and exact requested-patch/output agreement.

Each authorization record binds `patch_program_job_id`, repository, base commit, source/proposed branches, patch output checksum, reviewer identity/class/roles, decision, rationale and evidence into an immutable digest.

## Review governance

Reviewers must be distinct from requester and persisted patch producer and role-qualified for `security` or `operational`. The registry is immutable by `(manifest_digest, review_class)`: exact replay is idempotent and conflicting replacement fails closed. Completion requires approved operational and security records from two distinct reviewers.

Even complete review evidence grants no Git mutation, commit, push, PR creation, merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation authority.

## Validation

Dedicated CI compiles/lints the persisted-patch resolver and 114N surfaces and exercises manifest tampering, persisted patch checksum/identity mismatch, missing durable job identity, self-approval, role enforcement, stale manifests, immutable decisions, dual-review completion, reviewer conflict and rejection behavior.

Canonical issue #481 currently causes hosted jobs to terminate before step 1 with `steps=null`; this is infrastructure evidence only and does not satisfy the merge gate. The exact unchanged R4 head must receive executable focused validation and relevant parent/broad regressions before merge.

## Next dependency

BUILD-BRAIN-114P must be rebuilt directly on this exact R4 head before 114O/114Q/114R can again be considered authoritative. Actual Git/GitHub side effects remain a separate owner-governance boundary.
