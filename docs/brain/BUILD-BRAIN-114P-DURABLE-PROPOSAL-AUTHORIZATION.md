# BUILD-BRAIN-114P — Durable proposal-review authorization registry

## Objective

Persist BUILD-BRAIN-114N repository-proposal review evidence durably and verify it on every read without granting Calyx Git/GitHub mutation authority.

## Current lineage

This current-parent rebuild is based directly on the current-parent BUILD-BRAIN-114N branch. It supersedes historical PR #694, which was stacked on the stale 114N branch and therefore no longer represented the exact hardened 114M-R1 → 114N trust chain.

## Durable trust contract

`DurableProposalAuthorizationStore.record_review()` is the only public write path. It first invokes the governed 114N `ProposalAuthorizationBuilder`, which re-resolves the exact durable patch execution through `PersistedPatchExecutionService`, verifies manifest v2 and `patch_program_job_id`, enforces reviewer separation and role requirements, and only then persists the exact review decision.

Rows are immutable by `(manifest_digest, review_class)` and preserve the complete authorization payload plus SHA-256 authorization digest. Identical replay is idempotent; conflicting replacement fails closed, including uniqueness-race recovery.

Every read verifies payload schema, payload digest, row digest, row identity, allowed review class, and current durable patch evidence. If the underlying patch execution is missing, corrupted, or no longer matches the recorded proposal identity, the durable review cannot be materialized as valid evidence.

The durable store can materialize an in-memory 114N registry only from verified persisted rows, after which the existing dual-review status logic still requires independent operational and security approvals.

## Persistence

Forward-only migration `migrations/20260808_calyx_proposal_authorization_decisions.sql` creates the immutable decision table, unique `(manifest_digest, review_class)` constraint, unique authorization digest, and allowed review-class check. The migration is included but is not applied to production by this build.

## Validation

Focused tests exercise restart/reload, idempotent replay, conflicting replacement, payload and row tampering, durable patch-evidence loss/tampering, dual-review reconstruction, absence of a direct arbitrary-record API, self-approval rejection, unknown patch rejection, and invalid digest/review-class handling.

Dedicated CI is read-only and statically asserts the absence of Git/GitHub mutation primitives.

## Governance boundary

No Git command, branch creation, commit, push, pull-request creation, merge/auto-merge, deployment, scientific publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation is authorized by 114P.

Canonical CI incident #481 currently prevents hosted jobs from reaching step 1. This branch remains draft/unmerged until upstream 114M-R1 and 114N plus this exact head receive executable validation.

## Next dependency

BUILD-BRAIN-114O may consume only `DurableProposalAuthorizationStore` evidence for the exact manifest and must bind both durable authorization digests before owner authorization can exist.
