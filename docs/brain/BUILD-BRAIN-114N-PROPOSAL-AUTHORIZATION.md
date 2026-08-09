# BUILD-BRAIN-114N — Governed proposal authorization record

## Objective

Add immutable repository-proposal review evidence after BUILD-BRAIN-114M without granting Calyx Git or GitHub mutation authority.

## Current lineage

This R3 reconstruction is based directly on the current-main BUILD-BRAIN-114M-R2 replacement head `55bced0b862fa088a61db67580d95496f5eb3a2d` (PR #761). Historical 114N branches remain source material only because their parent lineage was stale. R3 carries only the six 114N authorization files on top of the exact R2 trust root.

## Hardened trust chain

114N accepts only `calyx-git-proposal-manifest-v2`. The manifest binds an exact durable `patch_program_job_id` plus repository, source autonomy branch, base commit, patch output checksum, proposed branch, change hashes, validation evidence, and manifest digest.

`ProposalAuthorizationBuilder` does not accept a caller-supplied patch receipt. Before creating review evidence it resolves the exact patch job through `PersistedPatchExecutionService`, backed by durable `CalyxProgramJob.evidence_json`. The R2 parent verifies durable assignment/program/job identity, canonical assignment input checksum, exact governed patch inputs against persisted output changes, and registered isolated-patch executor identity before any review evidence can be produced.

Each authorization record binds `patch_program_job_id` into its immutable payload and digest. Manifest v1 is rejected rather than grandfathered.

## Review governance

Reviewers must be distinct from requester and persisted patch producer, role-qualified for `security` or `operational`, and provide rationale, evidence URIs, and timezone-aware decision time.

`ProposalAuthorizationRegistry` keys decisions by `(manifest_digest, review_class)`. Identical replay is idempotent; conflicting replacement is rejected.

`proposal_review_status()` requires both review classes and two distinct reviewer identities. Rejection blocks completion; missing classes remain pending; same-reviewer dual approval is explicitly rejected as a reviewer conflict.

Even complete review evidence grants no Git mutation, commit, push, pull-request creation, automatic merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation authority.

## Validation contract

Dedicated CI compiles and lints the strengthened persisted-patch resolver together with both review surfaces and both focused test files. Focused regressions cover deterministic non-authority records, manifest tampering, persisted patch checksum/identity mismatch, missing durable patch-job identity, requester/producer self-approval, reviewer-role enforcement, stale manifests, immutable rejection, independent dual-review completion, reviewer conflict, and rejection behavior.

Static assertions require manifest v2, `PersistedPatchExecutionService`, bound `patch_program_job_id`, absence of a `patch_receipt` runtime path, and permanent non-authority flags.

## Current CI state

Canonical issue #481 continues to intermittently terminate GitHub-hosted jobs before workflow step 1 with `steps=null`. The exact 114M-R2 parent PR #761 reproduced that condition on its initial run and one retry. Such runs provide no compile, lint, pytest, or diff-hygiene evidence and are not interpreted as code failures or passes.

This branch must remain draft/unmerged until BUILD-BRAIN-114M-R2 is executable-green and this exact unchanged 114N R3 head executes and passes real workflow steps.

## Next dependency

BUILD-BRAIN-114P must be rebuilt only after this exact 114N layer is validated on the R2 trust root. Downstream 114O/114Q/114R then follow in order. Actual Git/GitHub mutation remains a separate owner-governance boundary.
