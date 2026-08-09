# BUILD-BRAIN-114R — Authorization-bound Git proposal execution plan

## Status

**IMPLEMENTED / VALIDATED on current canonical 114Q mainline.** PR #785 is reconstructed directly on merged BUILD-BRAIN-114Q `main` commit `f0c23c76425d52f9ade57711a9f9019a14787868`, not on the superseded pre-merge feature-stack ancestry. Historical #767 and earlier 114R branches are source material only.

Exact validated code head: `6086ac5449e12fcfc82917f54eac85a43535bd37`.

This Brain checkpoint records the actual failure-first repair sequence and changes no runtime behavior. It must itself receive applicable exact-head validation before merge.

## Objective

Compile the exact persisted, independently reviewed, externally owner-approved proposal evidence chain into a deterministic Git/GitHub plan while performing no repository mutation.

114R is the final evidence/planning layer before any future branch/commit/push/pull-request executor and intentionally stops at that governance boundary.

## Authoritative chain

`#772 BUILD-BRAIN-114M-R3 → #781 BUILD-BRAIN-114N-R6 → #782 BUILD-BRAIN-114P-R5 → #783 BUILD-BRAIN-114O-R5 → #784 BUILD-BRAIN-114Q-R5 → #785 BUILD-BRAIN-114R-R5`.

## Input trust chain

At plan time `GitProposalExecutionPlanner.build()`:

1. rebuilds the 114O authorization request from the exact manifest and current durable 114P review store;
2. compares that rebuilt request with the supplied request exactly;
3. rechecks manifest digest, durable `patch_program_job_id`, repository/base commit, **owner-authorized base ref**, proposal branch, postimage hashes, validation receipts, review digests, action set, and expiry;
4. re-verifies the owner grant through the 114Q Ed25519 public-key verifier; and
5. only then emits a deterministic plan.

The persisted patch receipt remains rooted in canonical assignment inputs from BUILD-BRAIN-114M-R3. Caller-supplied or synthetic patch receipt provenance cannot establish an authorized plan.

Missing, rejected, conflicted, tampered, expired, or changed evidence fails closed.

## Review remediation

### P1 — pull-request base branch binding — IMPLEMENTED / VALIDATED

The original plan carried `base_commit_sha` but not the target branch ref required by GitHub pull-request creation. 114R now makes `base_ref` a mandatory owner-authorized field in `GitMutationAuthorizationRequest`, includes it in the request digest and plan digest, validates it as a bounded Git ref distinct from the proposal branch, and carries it into `open_pull_request` alongside `base_commit_sha`.

A future executor therefore has no authority to guess the default branch or infer a branch from a commit SHA.

### P2 — frozen-plan snapshot mutation — IMPLEMENTED / VALIDATED

`GitProposalPlanOperation.payload()` now deep-copies nested operation parameters. A caller mutating a returned payload or snapshot cannot mutate the stored plan parameters or silently change the subsequent plan digest.

## Deterministic plan v2

`calyx-git-proposal-execution-plan-v2` binds the manifest digest, authorization request digest, durable patch job ID, repository, base commit, owner-authorized base ref, proposal branch, postimage hashes, validation and review digests, owner principal, grant expiry, verified signature-envelope digest, commit/PR metadata, and ordered operations.

The `create_commit` operation carries `patch_program_job_id`, eliminating inference about which durable patch execution supplies the authorized postimages.

Operations use canonical dependency order: `create_branch`, `create_commit`, `push_branch`, `open_pull_request`. Only dependency-closed prefixes are accepted. Sparse authorization that skips prerequisites fails closed.

## Failure-first repair record

The current-main reconstruction exposed real executable failures; none were hosted-runner failures:

1. **DEPENDENCY / CONTRACT + TEST** — making `base_ref` mandatory correctly broke inherited 114O/114Q fixtures that had not yet been migrated to the stronger authorization contract. Those fixtures were updated; `base_ref` was not weakened or defaulted.
2. **CODE / STYLE** — Ruff import ordering failed in the 114R regression surface and was corrected without behavioral change.
3. **CODE / STYLE** — Ruff required the deep-copy payload return to be reformatted. The deep-copy safety behavior was preserved exactly.
4. After those repairs, the focused behavioral planning suite, inherited 114O/114Q authorization suites, broad orchestration checks, publication-readiness regression, and workflow governance all reached executable code and passed.

## Validation

Exact code head `6086ac5449e12fcfc82917f54eac85a43535bd37` passed the applicable validation surface:

- BUILD-BRAIN-114R Git Proposal Execution Plan Validation `31329015792` — success; compile, Ruff lint/format, focused planning regressions, planning-only v2 provenance assertions, and diff hygiene passed.
- BUILD-BRAIN-114O Durable Reviewed Owner Authorization Validation `31329015795` — success.
- BUILD-BRAIN-114Q Owner Signature Verifier Validation `31329015819` — success; focused owner-verification regressions and public-key-only provenance checks passed.
- CALYX-AGENT-003 Validation `31329015798` — success.
- BUILD-088E Validation `31329015799` — success.
- CALYX Workflow Governance Audit `31329015822` — success.

Hosted GitHub Actions runners allocated and executed normally. These results are application/test validation evidence, not infrastructure-only outcomes.

## Permanent non-authorities

Every plan snapshot records `plan_only=true` and `git_mutation_performed=false`. This layer creates no branch, commit, push, or pull request. It contains no live Git/GitHub transport activation, merge mechanism, deployment authority, publication authority, taxonomy activation, production database mutation, or production Knowledge Graph mutation authority.

## Governance boundary

The next architectural step, BUILD-BRAIN-114S, executes real branch/commit/push/open-PR side effects through a mutation adapter. Activation or integration that materially expands Calyx's real Git/GitHub mutation control plane is an explicit owner-governance boundary. Merge/auto-merge, deployment, scientific publication, taxonomy activation, production database mutation, and production Knowledge Graph mutation remain separate authorities.
