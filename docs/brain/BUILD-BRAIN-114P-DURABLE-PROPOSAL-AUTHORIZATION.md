# BUILD-BRAIN-114P — Durable proposal-review authorization registry

## Objective

Persist BUILD-BRAIN-114N repository-proposal review evidence durably and verify it on every read without granting Calyx Git/GitHub mutation authority.

## Current lineage

This rebuild is based directly on strengthened BUILD-BRAIN-114N-R2 PR #747, itself rooted at the latest BUILD-BRAIN-114M-R1 durable patch-verification head. Historical #721 is no longer authoritative because its parent #719 was superseded after #696 materially strengthened runtime role scoping, assignment identity, canonical input-checksum verification, and exact patch input/output verification.

## Durable trust contract

`DurableProposalAuthorizationStore.record_review()` is the only public write path. It first invokes the governed 114N `ProposalAuthorizationBuilder`, which re-resolves the exact durable patch execution through `PersistedPatchExecutionService`, verifies manifest v2 and `patch_program_job_id`, enforces reviewer separation and role requirements, and only then persists the exact review decision.

Rows are immutable by `(manifest_digest, review_class)` and preserve the complete authorization payload plus SHA-256 authorization digest. Identical replay is idempotent; conflicting replacement fails closed, including uniqueness-race recovery.

Every read verifies payload schema, payload digest, row digest, row identity, allowed review class, and current durable patch evidence. Because the parent resolver is strengthened, materialization also depends on canonical assignment input checksum and exact governed patch-input/output agreement. If underlying patch execution is missing, corrupted, or no longer matches the recorded proposal identity, the durable review cannot be materialized as valid evidence.

The durable store can materialize an in-memory 114N registry only from verified persisted rows, after which dual-review status still requires independent operational and security approvals.

## Persistence

Forward-only migration `migrations/20260808_calyx_proposal_authorization_decisions.sql` creates the immutable decision table, unique `(manifest_digest, review_class)` constraint, unique authorization digest, and allowed review-class check. The migration is included but is not applied to production by this build.

## Integration correction

The historical 114P test fixture persisted a synthetic execution receipt with `input_checksum="input"`. That was sufficient before 114M-R1 added canonical assignment-input verification, but the strengthened parent now correctly rejects such a receipt. This rebuild updates the fixture to calculate `canonical_checksum(assignment_inputs_for_program_job(program, claimed))`, ensuring the durable-review tests exercise the same authoritative input object used by runtime execution.

## Validation

Focused tests exercise restart/reload, idempotent replay, conflicting replacement, payload and row tampering, durable patch-evidence loss/tampering, dual-review reconstruction, absence of a direct arbitrary-record API, self-approval rejection, unknown patch rejection, invalid digest/review-class handling, and the strengthened canonical assignment-input binding.

Dedicated CI is read-only and statically asserts the absence of Git/GitHub mutation primitives.

## Governance boundary

No Git command, branch creation, commit, push, pull-request creation, merge/auto-merge, deployment, scientific publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation is authorized by 114P.

Canonical CI incident #481 currently prevents hosted jobs from reaching step 1. This branch remains draft/unmerged until upstream 114M-R1 and 114N-R2 plus this exact head receive executable validation.

## Next dependency

BUILD-BRAIN-114O must be rebuilt on this exact 114P replacement and may consume only `DurableProposalAuthorizationStore` evidence for the exact manifest, binding both durable authorization digests before owner authorization can exist.
