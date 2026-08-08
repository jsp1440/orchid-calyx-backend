# BUILD-BRAIN-114N — Governed proposal authorization record

## Objective

Add immutable repository-proposal review evidence after merged BUILD-BRAIN-114M without granting Calyx Git or GitHub mutation authority.

## Current-main lineage

BUILD-BRAIN-114M is merged on `main` at `ab318d6d6c83d8cbfa8962bc9ef891ab14a96e3b`. The original 114N branch had accumulated 64 commits of mainline drift after that merge, so it was not retained as the authoritative integration branch. This slice is rebuilt directly from current `main` on `feature/brain-114n-current-main`; only 114N files belong in its delta.

## Trust chain

Before creating a decision record, 114N verifies:

1. the exact `calyx-git-proposal-manifest-v1` payload against its `manifest_digest`;
2. repository, base commit, source autonomy branch, proposed branch, and patch-output checksum;
3. an accompanying delivered receipt from exact executor `isolated_workspace_patcher_v1`;
4. receipt output checksum both against the manifest checksum and a fresh canonical checksum of the output;
5. receipt repository, branch, checkout commit, and authoritative isolated-patch mode against the manifest;
6. producer identity derived as `executor:isolated_workspace_patcher_v1`, never caller-supplied;
7. an independent reviewer distinct from requester and producer and holding the requested `security` or `operational` role;
8. non-empty rationale, evidence URIs, and a timezone-aware decision time.

The resulting `ProposalAuthorizationRecord` receives a deterministic `authorization_digest`.

## Immutable decisions

`ProposalAuthorizationRegistry` keys records by `(manifest_digest, review_class)`. Re-recording an identical record is idempotent. A conflicting later record is rejected. A rejection therefore cannot be silently replaced for the same exact proposal and review class. A changed proposal has a new manifest digest and requires new review.

## Dual-review completion

One approval is never sufficient for complete repository review evidence. `proposal_review_status()` requires both independent classes:

- one approved + one absent → `PROPOSAL_REVIEWS_PENDING`;
- any rejection → `PROPOSAL_REVIEW_REJECTED`;
- security approved + operational approved → `PROPOSAL_REVIEW_EVIDENCE_COMPLETE`.

Even `PROPOSAL_REVIEW_EVIDENCE_COMPLETE` is **not execution authorization**. The status fixes Git mutation, commit, push, pull-request creation, and automatic merge authority to false.

## Relationship to existing review governance

114N follows existing `ReviewRegistry` principles—immutable decisions, named review classes, role-qualified reviewers, and self-approval prohibition—but is narrower and cryptographically bound to 114M proposal/patch provenance. It does not replace scientific, licensing, publication, or release review.

## Permanent non-authorities

Neither an approved record nor completed dual-class review evidence authorizes:

- Git mutation;
- commit creation;
- push;
- pull-request creation;
- automatic merge;
- deployment;
- publication;
- taxonomy activation;
- production database mutation;
- production Knowledge Graph mutation.

114N runtime code invokes no Git command, shell, GitHub mutation API, network request, deployment system, publication system, or production mutation path.

## Validation contract

The dedicated read-only workflow compiles both 114N runtime surfaces, runs Ruff lint/format, executes focused record and aggregate-status regressions, statically asserts identity and non-authority boundaries, and runs event-aware diff hygiene.

Earlier validation attempts on the divergent predecessor branch failed before step 1 with `steps=null` across 114N and unchanged dependency workflows, so they are recorded as runner/allocation incidents and provide no code verdict. The current-main replacement must receive real workflow steps and pass exact-head validation before becoming review-ready.

Merge remains a separate repository governance decision.
