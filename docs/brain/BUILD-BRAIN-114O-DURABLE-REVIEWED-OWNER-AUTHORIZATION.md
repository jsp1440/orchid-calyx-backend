# BUILD-BRAIN-114O — Durable reviewed owner authorization

## Objective

Integrate BUILD-BRAIN-114O with the hardened BUILD-BRAIN-114P durable proposal-review store so a future repository-proposal executor cannot rely on process-local review objects or caller-constructed authorization records.

## Durable review chain

The gate accepts a `DurableProposalAuthorizationStore`, not an in-memory review registry supplied by the caller. 114P itself accepts review writes only through `record_review()`, which executes the governed 114N builder before persistence. For the exact 114M manifest digest, 114O then reloads only digest-verified persistent evidence, requires aggregate `PROPOSAL_REVIEW_EVIDENCE_COMPLETE`, verifies the exact persisted `operational` and `security` approvals, requires the appropriate role on each record, and requires distinct reviewer identities.

A standalone caller-constructed `ProposalAuthorizationRecord`, an unpersisted approval, a self-approval rejected by the governed 114P write path, or a tampered persisted row cannot satisfy the authorization gate.

## Request and owner-grant binding

The request is deterministically bound to the exact proposal manifest digest, repository/base commit, `autonomy/proposal/*` branch, every postimage hash, validation receipt digests, durable review authorization digests, explicit allowlisted action set, and an expiry no more than 30 minutes in the future.

The runtime gate is verifier-only. Owner grants must be produced outside this runtime surface. The signature must match the exact request digest, configured owner principal, and request expiry. The signed grant's own `issued_at → expires_at` lifetime must be positive and no longer than 30 minutes, preventing stale signed grants from being replayed into a later authorization window.

## Allowed future proposal actions

The authorization envelope can name only `create_branch`, `create_commit`, `push_branch`, and `open_pull_request`. This slice implements none of those mutations; it creates and verifies authorization evidence only.

## Permanent boundaries

No merge or auto-merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation authority is included. No Git command, subprocess, HTTP/GitHub mutation client, deployment system, publication system, or production-data mutation executor exists in the 114O runtime surface.

## Validation

The dedicated read-only workflow compiles the 114O and durable-store surfaces, Ruff-checks them, runs focused governed-persistence/review/owner-grant regressions, statically asserts verifier-only/non-mutation boundaries, and runs diff hygiene.

Canonical CI issue #481 currently records hosted jobs terminating before step 1 with `steps=null`. Such runs are not code verdicts. This slice remains draft until 114N, 114P, and this exact 114O head receive executable CI and pass.

## Governance boundary

Only after durable review evidence and executable validation are green should the project consider a bounded Git proposal executor that consumes this authorization and creates branch/commit/push/PR artifacts. Granting that repository mutation authority is a separate governance decision. Merge, deployment, publication, taxonomy activation, and production scientific-data mutation remain separate authorities even after proposal execution is enabled.
