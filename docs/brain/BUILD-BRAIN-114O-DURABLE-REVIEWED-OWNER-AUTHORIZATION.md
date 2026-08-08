# BUILD-BRAIN-114O — Durable reviewed owner authorization

## Objective

Integrate BUILD-BRAIN-114O with the durable BUILD-BRAIN-114P proposal-review store so a future repository-proposal executor cannot rely on process-local review objects as its authority source.

## Durable review chain

The gate accepts a `DurableProposalAuthorizationStore`, not an in-memory review registry supplied by the caller. For the exact 114M manifest digest it:

1. reloads persisted 114N records through 114P read-time digest and row-identity verification;
2. materializes aggregate review status only from those verified durable rows;
3. requires `PROPOSAL_REVIEW_EVIDENCE_COMPLETE`;
4. reloads the exact persisted `operational` and `security` decisions;
5. verifies both against the exact manifest, requires approval and role membership, and requires two distinct reviewer identities;
6. binds both persistent authorization digests into the owner authorization request.

A standalone caller-constructed `ProposalAuthorizationRecord`, an unpersisted approval, or a tampered persisted row cannot satisfy the gate.

## Request and owner-grant binding

The request remains bound to the exact proposal manifest digest, repository/base commit, `autonomy/proposal/*` branch, every postimage hash, validation receipt digests, durable review authorization digests, explicit allowlisted action set, and an expiry no more than 30 minutes in the future.

The runtime gate remains verifier-only. Owner grants must be produced outside this runtime surface and are accepted only when the signature matches the exact request digest, owner principal and expiry. Grant lifetime from `issued_at` to `expires_at` must itself be positive and no longer than 30 minutes, preventing stale signed grants from being replayed inside a later request window.

## Allowed future proposal actions

The authorization envelope can name only:

- `create_branch`;
- `create_commit`;
- `push_branch`;
- `open_pull_request`.

This slice does not implement any of those actions. It creates and verifies authorization evidence only.

## Permanent boundaries

No merge or auto-merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation authority is included. No Git command, subprocess, HTTP/GitHub mutation client, deployment system, publication system, or production data mutation executor exists in the 114O runtime surface.

## Validation

The dedicated read-only workflow compiles the 114O + durable-store surfaces, Ruff-checks them, runs focused durable-review/owner-grant regressions, statically proves verifier-only/non-mutation boundaries, and runs diff hygiene.

Canonical CI issue #481 currently records hosted jobs terminating before step 1 with `steps=null`. Such runs are not code verdicts. This slice remains draft until 114N, 114P and this exact 114O head receive executable CI and pass.

## Next governance boundary

Only after durable review evidence and executable validation are green should the project consider a bounded Git proposal executor that consumes this authorization and creates branch/commit/push/PR artifacts. Granting that mutation authority is a separate governance decision. Merge, deployment and production-science mutation remain separate authorities even after proposal execution is enabled.
