# BUILD-BRAIN-114N — Governed proposal authorization record

## Objective

Add immutable repository-proposal review evidence after merged BUILD-BRAIN-114M without granting Calyx Git or GitHub mutation authority.

## Current-main lineage

This slice is rebuilt directly from current `main` on `feature/brain-114n-current-main`; only 114N files belong in its functional delta.

## Trust chain

Before creating a decision record, 114N verifies the exact `calyx-git-proposal-manifest-v1` digest and proposal identity, the delivered `isolated_workspace_patcher_v1` receipt and checksum, and derives producer identity from that authoritative executor. Reviewers must be distinct from requester and producer, role-qualified for `security` or `operational`, and provide rationale, evidence URIs, and a timezone-aware decision time.

`ProposalAuthorizationRegistry` keys records by `(manifest_digest, review_class)`. Identical re-recording is idempotent; conflicting later decisions are rejected. Changed proposals require new review.

## Dual-review completion

`proposal_review_status()` requires both required classes. Missing evidence produces `PROPOSAL_REVIEWS_PENDING`; any rejection produces `PROPOSAL_REVIEW_REJECTED`; only approved security plus approved operational evidence produces `PROPOSAL_REVIEW_EVIDENCE_COMPLETE`.

Even complete review evidence grants no Git mutation, commit, push, pull-request creation, automatic merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation authority.

## CI provenance

CI-INFRA-002 (#685) currently causes selected PR jobs to terminate before checkout with `steps=null`. Such runs provide no code verdict. The exact-head 114N implementation remains draft until real workflow steps execute and pass.

## Next dependency

BUILD-BRAIN-114O may consume only authoritative 114N records retrieved from the registry for the exact manifest. It must require both approved classes from distinct reviewers before any owner-bound Git-proposal authorization request can exist. Actual Git/GitHub mutation remains a separate governance boundary.
