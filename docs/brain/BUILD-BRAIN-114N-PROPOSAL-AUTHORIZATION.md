# BUILD-BRAIN-114N — Governed proposal authorization record

## Objective

Add immutable repository-proposal review evidence after merged BUILD-BRAIN-114M without granting Calyx Git or GitHub mutation authority.

## Current-main lineage

This slice is rebuilt directly from current `main` on `feature/brain-114n-current-main`; only 114N files and CI-incident documentation belong in its delta. Superseded divergent PR #684 was closed unmerged; PR #687 is the single authoritative implementation for issue #683.

## Trust chain

Before creating a decision record, 114N verifies the exact `calyx-git-proposal-manifest-v1` digest and proposal identity, the delivered `isolated_workspace_patcher_v1` receipt and checksum, and derives producer identity from that authoritative executor. Reviewers must be distinct from requester and producer, role-qualified for `security` or `operational`, and provide rationale, evidence URIs, and a timezone-aware decision time.

`ProposalAuthorizationRegistry` keys records by `(manifest_digest, review_class)`. Identical re-recording is idempotent; conflicting later decisions are rejected. Changed proposals require new review.

## Dual-review completion

`proposal_review_status()` requires both required review classes **and two distinct reviewer identities**. Missing evidence produces `PROPOSAL_REVIEWS_PENDING`; any rejection produces `PROPOSAL_REVIEW_REJECTED`; two approved classes recorded by the same reviewer produce `PROPOSAL_REVIEW_REVIEWER_CONFLICT`; only security plus operational approval from distinct reviewers produces `PROPOSAL_REVIEW_EVIDENCE_COMPLETE`.

This independent-review hardening closes a governance gap found during structural audit: a principal holding both reviewer roles can no longer single-handedly complete the repository proposal review-evidence gate.

Even complete review evidence grants no Git mutation, commit, push, pull-request creation, automatic merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation authority.

## Validation and CI provenance

The dedicated 114N workflow compiles both runtime surfaces and both focused test files, runs Ruff lint and format verification, executes focused pytest regressions, asserts non-mutation boundaries plus the independent-review conflict path, and runs diff hygiene.

GitHub-hosted Actions is currently terminating selected repository jobs before checkout with `steps=null`. A controlled rerun of the focused 114N gate reproduced the same pre-step failure. Such runs provide no compile, lint, pytest, or diff-hygiene verdict and are not application failures. The exact-head 114N implementation remains draft until a runner executes real workflow steps and passes.

The local environment available to the coordinator does not provide `gh` and has no outbound repository network access, so it cannot substitute an authenticated checkout for hosted CI. Structural source review remains useful for governance defects but is not represented as executable validation.

## Next dependency

BUILD-BRAIN-114O may consume only authoritative 114N records retrieved from the registry for the exact manifest. It must require both approved classes from distinct reviewers before any owner-bound Git-proposal authorization request can exist. Actual Git/GitHub mutation remains a separate governance boundary, and 114O must not be treated as review-ready until 114N receives executable exact-head validation.
