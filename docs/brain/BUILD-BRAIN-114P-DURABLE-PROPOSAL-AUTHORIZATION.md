# BUILD-BRAIN-114P — Durable proposal-review authorization registry

## Status

R5 reconstruction directly on BUILD-BRAIN-114N-R6 PR #781 exact validated head `079cf0bd003092767742ec63d5469dd069105fd4`. Draft and unmerged. Parent exact-head BUILD-BRAIN-114N, CALYX-AGENT-003, and Workflow Governance validation are green.

## Objective

Persist governed repository-proposal review evidence durably and verify it on every read without granting Calyx Git/GitHub mutation authority.

## Current lineage

`#772 BUILD-BRAIN-114M-R3 → #781 BUILD-BRAIN-114N-R6 → this BUILD-BRAIN-114P-R5`.

The parent chain includes canonical assignment inputs, durable execution identity, canonical receipt input-checksum recomputation, exact governed patch input/output agreement, manifest v2, `patch_program_job_id`, requester/producer separation, role-qualified operational/security review semantics, immutable per-class review evidence, and distinct-reviewer completion requirements.

Historical #780 / R4 is rooted in stale #778 and is source material only. R5 reapplies the six additive durable-review files directly on the exact validated #781 head rather than carrying obsolete ancestry.

## Durable trust contract

`DurableProposalAuthorizationStore.record_review()` is the governed write path. It invokes the 114N builder, re-resolves the exact durable patch through `PersistedPatchExecutionService`, verifies manifest v2 and patch-job identity, enforces reviewer separation and roles, and only then persists the decision.

Rows are immutable by `(manifest_digest, review_class)` and preserve the full authorization payload plus SHA-256 digest. Exact replay is idempotent; conflicting replacement and uniqueness races fail closed. Every read verifies schema, payload digest, row digest, row identity, review class and current durable patch evidence.

## Persistence

The forward-only migration creates the immutable decision table, unique manifest/class pair, unique authorization digest, and allowed review-class check. It is included but not applied to production. Applying this migration remains outside this implementation slice.

## Canonical assignment-input binding

The durable-review fixture computes the execution receipt input checksum with `canonical_checksum(assignment_inputs_for_program_job(program, claimed))`. This is the same authoritative input object used by the current 114M-R3 runtime path; placeholder receipt checksums cannot satisfy the trust chain.

## Validation

Focused regressions cover durable reload, idempotent replay, conflicting replacement, payload/row and patch-evidence tampering, dual-review reconstruction, self-approval, missing patch evidence, and canonical assignment-input binding. Dedicated CI is read-only, validates the migration contract, and statically rejects Git/GitHub mutation primitives.

R5 requires executable exact-head BUILD-BRAIN-114P validation plus relevant parent/broad regressions before any downstream reconstruction. Failures are fixed before expansion.

## Governance boundary

No Git command, branch creation, commit, push, pull-request creation, merge/auto-merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation is authorized. The migration is not applied by this slice.

## Next dependency

BUILD-BRAIN-114O must be rebuilt directly on this exact validated R5 head before owner authorization, public-key verification, and plan-only 114R can again be authoritative. Actual Git/GitHub side-effect execution remains a separate owner-governance decision.
