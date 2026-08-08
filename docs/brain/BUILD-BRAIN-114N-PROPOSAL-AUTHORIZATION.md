# BUILD-BRAIN-114N — Governed proposal authorization record

## Objective

Add an immutable review/authorization evidence layer after BUILD-BRAIN-114M without granting Calyx any Git or GitHub mutation authority. 114N binds a reviewer decision to the exact proposal manifest and the authoritative isolated-patch provenance that produced it.

## Trust chain

114N verifies the following chain before creating a decision record:

1. the supplied 114M manifest carries `calyx-git-proposal-manifest-v1` and its `manifest_digest` exactly matches its canonical payload;
2. the manifest repository, base commit, source autonomy branch, proposed branch, and patch-output checksum are captured as immutable decision identity;
3. the accompanying patch receipt must be delivered by the exact authoritative `isolated_workspace_patcher_v1` executor;
4. the receipt output checksum must both equal the manifest patch-output checksum and recompute over the exact receipt output;
5. receipt repository, autonomy branch, checkout commit, and patch mode must match the manifest;
6. producer identity is derived as `executor:isolated_workspace_patcher_v1`, never supplied independently by the caller;
7. reviewer identity must differ from both the request principal and the derived producer, and the reviewer must hold the requested review-class role;
8. the review class is restricted to `security` or `operational` for repository proposal authorization evidence;
9. rationale, evidence URIs, and timezone-aware decision timestamp are required;
10. the resulting record receives a deterministic SHA-256 `authorization_digest`.

## Immutable decision semantics

`ProposalAuthorizationRegistry` keys decisions by `(manifest_digest, review_class)`. Re-recording the identical decision is idempotent. A conflicting later decision for the same manifest/review class is rejected as `PROPOSAL_AUTH_AUTHORITATIVE_DECISION_ALREADY_RECORDED`.

This makes rejection terminal for that exact manifest/review class and prevents an approval from silently replacing it. Any changed proposal produces a different manifest digest and requires a new review record. `ProposalAuthorizationRecord.verify_for_manifest()` rejects an old record against a newly digested manifest as stale.

## Relationship to existing Calyx review governance

The design follows the existing `ReviewRegistry` principles: immutable review decisions, named review classes, role-qualified reviewers, and self-approval prohibition. 114N is narrower: it is specifically bound to 114M Git proposal artifacts and derives the patch producer from authoritative execution provenance rather than trusting a caller-provided producer identity.

114N does not replace scientific review, licensing review, publication review, or release eligibility. It creates repository-proposal review evidence only.

## Permanent non-authorities

An `approved` 114N record is **not** an execution capability. Every record explicitly carries false authority for:

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

No runtime code in 114N invokes Git, a shell, GitHub mutation APIs, network requests, deployment systems, publication systems, or production data mutation paths.

## Validation contract

The dedicated `BUILD-BRAIN-114N Proposal Authorization Validation` workflow is read-only and runs:

- Python compilation;
- Ruff lint and format verification;
- focused authorization regressions;
- static assertions for producer derivation, self-approval/stale-manifest rejection, and permanent non-authorities;
- event-aware `git diff --check` hygiene.

BUILD-BRAIN-114M is now merged to `main` at `ab318d6d6c83d8cbfa8962bc9ef891ab14a96e3b`. PR #684 has therefore been retargeted directly to current `main`; it no longer depends on the historical #667 PR branch. Exact-head validation against this current-main merge context is required before 114N can become review-ready. Merge remains a separate repository governance decision.

## CI provenance

The first PR-head matrix on `71ec524df0c2303f1cfa6650b446b9c19166e939` did not execute repository code. BUILD-BRAIN-114N run #1 (`31280952477`), CALYX-AGENT-003 run #275 (`31280952414`), and CALYX Workflow Governance run #536 (`31280952387`) each produced a failed job with `steps=null`; the 114N job log blob was not created. This is recorded as a pre-step runner/allocation incident, not a code/test failure. No validation claim is made from that attempt.

This Brain update records the corrected current-main lineage and intentionally retriggers the PR matrix without changing 114N runtime behavior. The next run that receives real workflow steps is authoritative for compile/lint/test status.
