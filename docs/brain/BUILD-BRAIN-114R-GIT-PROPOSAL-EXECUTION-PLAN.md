# BUILD-BRAIN-114R — Authorization-bound Git proposal execution plan

## Status

**IMPLEMENTED / VALIDATED on current canonical 114Q mainline.** PR #785 is reconstructed directly on merged BUILD-BRAIN-114Q `main` commit `f0c23c76425d52f9ade57711a9f9019a14787868`, not on the superseded pre-merge feature-stack ancestry. Historical #767 and earlier 114R branches are source material only.

Exact validated code head: `f1ee23de67166050681f54e7c8b22f1f6623eb3d`.

Final Brain-documented head `712197af9724a9864cd8518354f529b76c008245` passed all six applicable exact-head workflows before merge readiness.

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

`GitProposalPlanOperation.payload()` deep-copies nested operation parameters. A caller mutating a returned payload or snapshot cannot mutate the stored plan parameters or silently change the subsequent plan digest.

### Signature text canonicalization — IMPLEMENTED / VALIDATED

A failure-first regression exposed a Base64URL equivalence edge case: modifying unused trailing encoding bits can produce different text that decodes to identical Ed25519 signature bytes. The public-key verifier now accepts only unpadded canonical Base64URL text by decoding and re-encoding before verification. One signature byte sequence therefore has one accepted textual representation. This preserves cryptographic byte verification while removing textual ambiguity in signature identity and audit evidence.

## Deterministic plan v2

`calyx-git-proposal-execution-plan-v2` binds the manifest digest, authorization request digest, durable patch job ID, repository, base commit, owner-authorized base ref, proposal branch, postimage hashes, validation and review digests, owner principal, grant expiry, verified signature-envelope digest, commit/PR metadata, and ordered operations.

The `create_commit` operation carries `patch_program_job_id`, eliminating inference about which durable patch execution supplies the authorized postimages.

Operations use canonical dependency order: `create_branch`, `create_commit`, `push_branch`, `open_pull_request`. Only dependency-closed prefixes are accepted. Sparse authorization that skips prerequisites fails closed.

## Failure-first repair record

The current-main reconstruction exposed real executable findings; none were hosted-runner failures:

1. **DEPENDENCY / CONTRACT + TEST** — mandatory `base_ref` correctly broke inherited 114O/114Q fixtures that had not yet migrated to the stronger authorization contract. The fixtures were updated; `base_ref` was not weakened or defaulted.
2. **CODE / STYLE** — Ruff import ordering failed in the 114R regression surface and was corrected without behavioral change.
3. **CODE / STYLE** — Ruff required the deep-copy payload return to be reformatted. Deep-copy safety behavior was preserved exactly.
4. **TEST / CRYPTO ENCODING** — an invalid-signature test changed only the final Base64URL character and could accidentally preserve the same decoded signature bytes. Rather than rely on ambiguous textual aliases, the 114Q verifier was strengthened to require canonical unpadded Base64URL encodings. The inherited 114Q suite and 114R planning suite both pass under the stronger rule.

## Validation

Exact code head `f1ee23de67166050681f54e7c8b22f1f6623eb3d` passed all applicable validation:

- BUILD-BRAIN-114R Git Proposal Execution Plan Validation `31329145290` — success.
- BUILD-BRAIN-114O Durable Reviewed Owner Authorization Validation `31329145280` — success.
- BUILD-BRAIN-114Q Owner Signature Verifier Validation `31329145260` — success.
- CALYX-AGENT-003 Validation `31329145281` — success.
- BUILD-088E Validation `31329145283` — success.
- CALYX Workflow Governance Audit `31329145278` — success.

Final Brain-documented head `712197af9724a9864cd8518354f529b76c008245` also passed all six applicable exact-head workflows:

- BUILD-BRAIN-114R `31329195937` — success.
- BUILD-BRAIN-114O `31329195893` — success.
- BUILD-BRAIN-114Q `31329195895` — success.
- CALYX-AGENT-003 `31329195918` — success.
- BUILD-088E `31329195915` — success.
- CALYX Workflow Governance Audit `31329195926` — success.

Hosted GitHub Actions runners allocated and executed normally. These are application/test validation results, not infrastructure-only outcomes.

## Permanent non-authorities

Every plan snapshot records `plan_only=true` and `git_mutation_performed=false`. This layer creates no branch, commit, push, or pull request. It contains no live Git/GitHub transport activation, merge mechanism, deployment authority, publication authority, taxonomy activation, production database mutation, or production Knowledge Graph mutation authority.

## Governance boundary

The next architectural step, BUILD-BRAIN-114S, executes real branch/commit/push/open-PR side effects through a mutation adapter. Activation or integration that materially expands Calyx's real Git/GitHub mutation control plane is an explicit owner-governance boundary. Merge/auto-merge, deployment, scientific publication, taxonomy activation, production database mutation, and production Knowledge Graph mutation remain separate authorities.
