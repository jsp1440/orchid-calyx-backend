# BUILD-BRAIN-114N — Governed proposal authorization record

## Status

R4B reconstruction directly on BUILD-BRAIN-114M-R3 PR #772 exact head `06f3bc3a98d579af62906dd463609968b7bf23f2`. Draft and unmerged pending executable CI.

## Objective

Add immutable repository-proposal review evidence after BUILD-BRAIN-114M without granting Calyx Git or GitHub mutation authority.

## Current lineage

This branch starts from the latest #772 trust-root head after its documentation-only lineage update. The parent remains the current-main reconstruction of hardened BUILD-BRAIN-114M: canonical assignment inputs, role-scoped `workspace_write`, durable receipt identity, canonical input-checksum recomputation, exact governed patch input/output agreement, persisted sandbox-validation authority, and manifest v2 bound to `patch_program_job_id`.

The 114N layer is additive-only. Historical #761/#762 and the first R4 reconstruction rooted one documentation commit behind #772 are not authoritative merge candidates.

## Hardened trust chain

114N accepts only `calyx-git-proposal-manifest-v2`. `ProposalAuthorizationBuilder` accepts no caller-supplied patch receipt. Before producing review evidence it re-resolves the exact durable patch through `PersistedPatchExecutionService`, inheriting the parent trust checks over program/job/assignment identity, canonical input checksum, registered executor, output checksum, and requested-patch/output equality.

Each authorization record cryptographically binds the manifest digest, durable `patch_program_job_id`, repository, base commit, source and proposed branches, patch output checksum, producer identity, requester, review class, reviewer identity and roles, decision, rationale, evidence URIs, and decision timestamp.

## Review governance

Only `operational` and `security` review classes are accepted. A reviewer must hold the matching role and must be distinct from both the requester and persisted patch producer. The in-memory registry is immutable per `(manifest_digest, review_class)`: exact replay is idempotent and conflicting replacement fails closed. Review completion requires approved operational and security evidence from two distinct reviewers; any rejection, missing class, or reviewer collision leaves the proposal incomplete.

Even complete review evidence grants no Git mutation, commit, push, PR creation, automatic merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation authority.

## Validation

The dedicated workflow compiles and lints the persisted-patch resolver plus both 114N surfaces, runs focused authorization/status regressions, asserts manifest-v2 and durable-patch identity binding, rejects caller patch-receipt authority, and statically confirms all repository mutation authorities remain false.

Canonical hosted-runner incident #481 is still active. Jobs that terminate with `steps=null` before checkout are infrastructure evidence only and do not satisfy the merge gate. The exact unchanged R4B head must receive executable focused validation and relevant parent/broad regression coverage before merge.

## Next dependency

BUILD-BRAIN-114P must be rebuilt directly on this exact R4B head before durable reviews, owner authorization, public-key verification, and execution planning can be considered current. Actual Git/GitHub side effects remain a separate explicit owner-governance boundary.
