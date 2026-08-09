# BUILD-BRAIN-114N — Governed proposal authorization record

## Status

R6 reconstruction directly on BUILD-BRAIN-114M-R3 PR #772 exact validated head `933d116513f1d439dce4004b079752fc4879a8cd`. Draft and unmerged. Parent exact-head validation is green across BUILD-BRAIN-114M, BUILD-BRAIN-114A, BUILD-BRAIN-108-113A, BUILD-BRAIN-114I, BUILD-088E, CALYX-AGENT-003, and Workflow Governance.

## Objective

Add immutable repository-proposal review evidence after BUILD-BRAIN-114M without granting Calyx Git or GitHub mutation authority.

## Current lineage

This branch starts from the latest #772 trust-root head after formatter remediation and the user-authored exact-head validation trigger. The parent remains the current-main reconstruction of hardened BUILD-BRAIN-114M: canonical assignment inputs, role-scoped `workspace_write`, durable receipt identity, canonical input-checksum recomputation, exact governed patch input/output agreement, persisted sandbox-validation authority, and manifest v2 bound to `patch_program_job_id`.

Historical #778 / R4B was rebuilt on an earlier #772 head and became non-mergeable after the parent advanced. R6 therefore reapplies only the six additive 114N files directly on the exact validated parent head. Historical #761/#762/#771/#778 lineages are source material only and are not authoritative merge candidates.

## Hardened trust chain

114N accepts only `calyx-git-proposal-manifest-v2`. `ProposalAuthorizationBuilder` accepts no caller-supplied patch receipt. Before producing review evidence it re-resolves the exact durable patch through `PersistedPatchExecutionService`, inheriting the parent trust checks over program/job/assignment identity, canonical input checksum, registered executor, output checksum, and requested-patch/output equality.

Each authorization record cryptographically binds the manifest digest, durable `patch_program_job_id`, repository, base commit, source and proposed branches, patch output checksum, producer identity, requester, review class, reviewer identity and roles, decision, rationale, evidence URIs, and decision timestamp.

## Review governance

Only `operational` and `security` review classes are accepted. A reviewer must hold the matching role and must be distinct from both the requester and persisted patch producer. The in-memory registry is immutable per `(manifest_digest, review_class)`: exact replay is idempotent and conflicting replacement fails closed. Review completion requires approved operational and security evidence from two distinct reviewers; any rejection, missing class, or reviewer collision leaves the proposal incomplete.

Even complete review evidence grants no Git mutation, commit, push, PR creation, automatic merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation authority.

## Validation

The dedicated workflow compiles and lints the persisted-patch resolver plus both 114N surfaces, runs focused authorization/status regressions, asserts manifest-v2 and durable-patch identity binding, rejects caller patch-receipt authority, and statically confirms all repository mutation authorities remain false.

GitHub-hosted Actions have resumed executable operation. Parent #772 exact head `933d116513f1d439dce4004b079752fc4879a8cd` passed all seven triggered validation lanes. R6 requires its own executable exact-head BUILD-BRAIN-114N validation and relevant parent/broad regression coverage before it can become a merge candidate.

## Next dependency

BUILD-BRAIN-114P must be rebuilt directly on the exact validated 114N reconstruction before durable reviews, owner authorization, public-key verification, and execution planning can be considered current. Actual Git/GitHub side effects remain a separate explicit owner-governance boundary.
