# BUILD-BRAIN-114N — Governed proposal authorization record

## Objective

Add immutable repository-proposal review evidence after BUILD-BRAIN-114M without granting Calyx Git or GitHub mutation authority.

## Current lineage

PR #687 is the authoritative BUILD-BRAIN-114N implementation for issue #683. After trust audit issue #692 identified that merged 114M v1 accepted caller-supplied patch receipts, #687 was retargeted onto corrective BUILD-BRAIN-114M-R1 PR #696. It must not merge before #696.

## Hardened trust chain

114N accepts only `calyx-git-proposal-manifest-v2`. The manifest must bind an exact durable `patch_program_job_id` plus repository, source autonomy branch, base commit, patch output checksum, proposed branch, change hashes, validation evidence, and its manifest digest.

`ProposalAuthorizationBuilder` no longer accepts a caller-supplied patch receipt. Before creating any review record it resolves the exact patch job through `PersistedPatchExecutionService`, which is backed by durable `CalyxProgramJob.evidence_json`. The persisted execution must match the manifest repository, source branch, base commit, output checksum, and authoritative isolated-patcher executor identity. Producer identity is derived from that persisted executor.

This closes the downstream version of the 114M-R1 trust defect: a syntactically valid manifest plus fabricated in-memory patch receipt cannot create review evidence.

Each authorization record binds `patch_program_job_id` into its immutable payload and authorization digest. A pre-fix v1 manifest is rejected rather than silently grandfathered.

## Review governance

Reviewers must be distinct from requester and persisted patch producer, role-qualified for `security` or `operational`, and provide rationale, evidence URIs, and a timezone-aware decision time.

`ProposalAuthorizationRegistry` keys records by `(manifest_digest, review_class)`. Identical re-recording is idempotent; conflicting later decisions are rejected. Changed proposals require new review.

`proposal_review_status()` requires both required review classes **and two distinct reviewer identities**. Missing evidence produces `PROPOSAL_REVIEWS_PENDING`; any rejection produces `PROPOSAL_REVIEW_REJECTED`; two approved classes recorded by the same reviewer produce `PROPOSAL_REVIEW_REVIEWER_CONFLICT`; only security plus operational approval from distinct reviewers produces `PROPOSAL_REVIEW_EVIDENCE_COMPLETE`.

Even complete review evidence grants no Git mutation, commit, push, pull-request creation, automatic merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation authority.

## Validation contract

The dedicated 114N workflow now compiles and lints the persisted-patch resolver together with both runtime review surfaces and both focused test files. Focused regressions cover deterministic non-authority records, manifest tampering, persisted patch checksum/identity mismatch, missing durable patch-job identity, requester/producer self-approval, reviewer-role enforcement, stale manifests, immutable rejection, independent dual-review completion, and rejection behavior.

Static assertions require manifest v2, `PersistedPatchExecutionService`, bound `patch_program_job_id`, absence of a `patch_receipt` runtime path, and permanent non-authority flags.

## Current CI incident

Canonical issue #481 records a repository-wide GitHub-hosted runner allocation failure. A zero-dependency diagnostic workflow containing only one shell `echo` step failed before step 1 with `steps=null`, ruling out repository code, Python/PostgreSQL setup, checkout/setup actions, and third-party actions as the immediate cause. Such runs provide no compile, lint, pytest, or diff-hygiene verdict and are not application failures.

Keep #687 draft until #696 is executable-green and #687's exact stacked head receives real workflow steps and passes.

## Next dependency

BUILD-BRAIN-114O may consume only authoritative 114N registry records for the exact v2 manifest, including the bound durable patch-job identity. It must require both approved classes from distinct reviewers before an owner-bound Git-proposal authorization request can exist. Actual Git/GitHub mutation remains a separate governance boundary.
