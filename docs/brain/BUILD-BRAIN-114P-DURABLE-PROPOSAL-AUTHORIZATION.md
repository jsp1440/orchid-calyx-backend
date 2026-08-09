# BUILD-BRAIN-114P — Durable proposal-review authorization registry

## Status

R3 reconstruction directly on BUILD-BRAIN-114N-R3 PR #762, itself rooted in current-main BUILD-BRAIN-114M-R2 PR #761. Draft and unmerged pending executable CI.

## Objective

Persist governed repository-proposal review evidence durably and verify it on every read without granting Calyx Git/GitHub mutation authority.

## Current lineage

`#761 BUILD-BRAIN-114M-R2 → #762 BUILD-BRAIN-114N-R3 → this BUILD-BRAIN-114P-R3`.

The parent chain includes canonical assignment inputs, durable execution identity, canonical receipt input-checksum recomputation, exact governed patch input/output agreement, manifest v2, `patch_program_job_id`, requester/producer separation, and independent operational/security review semantics.

## Durable trust contract

`DurableProposalAuthorizationStore.record_review()` is the governed write path. It invokes the 114N builder, re-resolves the exact durable patch through `PersistedPatchExecutionService`, verifies manifest v2 and patch-job identity, enforces reviewer separation and roles, and only then persists the decision.

Rows are immutable by `(manifest_digest, review_class)` and preserve the full authorization payload plus SHA-256 digest. Exact replay is idempotent; conflicting replacement and uniqueness races fail closed. Every read verifies schema, payload digest, row digest, row identity, review class and current durable patch evidence.

## Persistence

The forward-only migration creates the immutable decision table, unique manifest/class pair, unique authorization digest, and allowed review-class check. It is included but not applied to production.

## Canonical assignment-input correction

The durable-review fixture computes the execution receipt input checksum with `canonical_checksum(assignment_inputs_for_program_job(program, claimed))`. This is the same authoritative input object used by the strengthened current-main 114M-R2 runtime path; placeholder receipt checksums cannot satisfy the trust chain.

## Validation

Focused regressions cover durable reload, idempotent replay, conflicting replacement, payload/row and patch-evidence tampering, dual-review reconstruction, self-approval, missing patch evidence, and canonical assignment-input binding. Dedicated CI is read-only and statically rejects Git/GitHub mutation primitives.

Canonical incident #481 currently causes hosted jobs to terminate before step 1 with `steps=null`; such runs are infrastructure evidence only.

## Governance boundary

No Git command, branch creation, commit, push, pull-request creation, merge/auto-merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation is authorized.

## Next dependency

BUILD-BRAIN-114O must be rebuilt directly on this exact R3 head before public-key verification and plan-only 114R can again be authoritative. Actual Git/GitHub side-effect execution remains a separate owner-governance decision.
