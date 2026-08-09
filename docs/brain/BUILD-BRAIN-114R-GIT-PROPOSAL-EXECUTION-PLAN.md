# BUILD-BRAIN-114R — Authorization-bound Git proposal execution plan

## Status

R5 reconstruction directly on exact validated BUILD-BRAIN-114Q-R5 PR #784 head `dd54600a48eb6f9be4e4475c41b1d31ce4dee6a6`. Draft integration only. Historical #767 is source material, not an integration path.

Implementation head `8ec022e5aa93002f9a22a2bc5582ace6d3f25aa1` received executable exact-head focused and broad validation after correcting Ruff-only formatting findings. This documentation checkpoint changes no runtime behavior and must itself receive applicable read-only validation before 114R is considered complete.

## Objective

Compile the exact persisted, independently reviewed, externally owner-approved proposal evidence chain into a deterministic Git/GitHub plan while performing no repository mutation.

114R is the final evidence/planning layer before any future branch/commit/push/pull-request executor and intentionally stops at that governance boundary.

## Authoritative R5 chain

`#772 BUILD-BRAIN-114M-R3 → #781 BUILD-BRAIN-114N-R6 → #782 BUILD-BRAIN-114P-R5 → #783 BUILD-BRAIN-114O-R5 → #784 BUILD-BRAIN-114Q-R5 → #785 BUILD-BRAIN-114R-R5`.

## Input trust chain

At plan time `GitProposalExecutionPlanner.build()`:

1. rebuilds the 114O request from the exact manifest and current durable 114P review store;
2. compares that rebuilt request with the supplied request exactly;
3. rechecks manifest digest, durable `patch_program_job_id`, repository/base commit, proposal branch, postimage hashes, validation receipts, review digests, action set, and expiry;
4. re-verifies the owner grant through the 114Q Ed25519 public-key verifier; and
5. only then emits a deterministic plan.

The persisted patch receipt remains rooted in canonical assignment inputs from BUILD-BRAIN-114M-R3. Focused regressions reconstruct `input_checksum=canonical_checksum(assignment_inputs_for_program_job(program, claimed))`; caller-supplied or synthetic patch receipt provenance cannot establish an authorized plan.

Missing, rejected, conflicted, tampered, expired, or changed evidence fails closed.

## Deterministic plan v2

`calyx-git-proposal-execution-plan-v2` binds the manifest digest, authorization request digest, durable patch job ID, repository/base commit, proposal branch, postimage hashes, validation and review digests, owner principal, grant expiry, verified signature-envelope digest, commit/PR metadata, and ordered operations.

The `create_commit` operation carries `patch_program_job_id`, eliminating inference about which durable patch execution supplies the authorized postimages.

Operations use canonical dependency order: `create_branch`, `create_commit`, `push_branch`, `open_pull_request`. Only dependency-closed prefixes are accepted. Sparse authorization that skips prerequisites fails closed.

## Permanent non-authorities

Every plan snapshot records `plan_only=true` and `git_mutation_performed=false`. This layer creates no branch, commit, push, or pull request. It contains no subprocess Git execution, GitHub mutation client, token loader, merge mechanism, deployment client, publication client, taxonomy activation, production database mutation, or production Knowledge Graph mutation authority.

## Validation

Dedicated read-only CI compiles and Ruff-checks the 114R planning surface, runs focused 114R + 114Q + 114O regressions, verifies canonical persisted-input provenance, asserts the absence of mutation implementation markers, and checks diff hygiene.

Exact implementation head `8ec022e5aa93002f9a22a2bc5582ace6d3f25aa1` completed all applicable PR-triggered validation successfully:

- BUILD-BRAIN-114R Git Proposal Execution Plan Validation run `31297652976` — success. Checkout, Python setup, dependency install, compile, Ruff lint/format, focused planning regressions, v2 provenance/non-mutation assertions, and diff hygiene all passed.
- CALYX Workflow Governance Audit run `31297652972` — success.
- CALYX-AGENT-003 Validation run `31297652970` — success.

Earlier executable 114R runs exposed only code-quality formatting findings. The initial run identified import formatting; the next identified two remaining Ruff-format transforms. Those findings were corrected before the successful exact implementation-head run.

No expansion into BUILD-BRAIN-114S is permitted by this build. After this documentation checkpoint is green, further implementation stops at the explicit owner-governance boundary.

## Governance boundary

The next architectural step would execute real branch/commit/push/open-PR side effects. That is deliberately outside 114R and requires a separate explicit owner governance decision. Merge/auto-merge, deployment, scientific publication, taxonomy activation, production database mutation, and production Knowledge Graph mutation remain separate authorities even if proposal execution is later authorized.
