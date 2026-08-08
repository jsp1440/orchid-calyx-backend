# BUILD-BRAIN-114P — Durable proposal-review authorization registry

## Objective

Close the persistence gap between BUILD-BRAIN-114N review evidence and any future repository-mutation executor. The original 114N `ProposalAuthorizationRegistry` is deterministic and immutable within one process, but it is not durable across worker restart, failover, or multi-process operation. 114P introduces a durable evidence store before any real Git/GitHub mutation authority is considered.

## Persistence contract

`calyx_proposal_authorization_decisions` stores one immutable decision for each exact `(manifest_digest, review_class)` pair. The database enforces that pair as unique and also keeps `authorization_digest` unique. Review classes are restricted to `operational` and `security`.

`DurableProposalAuthorizationStore.record()` is idempotent for an identical decision. If a competing writer wins the uniqueness race, the loser rolls back, reloads the winning row, verifies it, and returns it only if it is exactly the same decision. A different decision for the same manifest/review class fails closed as `PROPOSAL_AUTH_DURABLE_DECISION_ALREADY_RECORDED`.

## Read-time verification

Persistent rows are never trusted merely because they exist. Every read:

1. parses the stored JSON object;
2. verifies schema `calyx-proposal-authorization-v1`;
3. recomputes the canonical SHA-256 authorization digest over the payload;
4. verifies the recomputed digest against the payload digest and the dedicated row digest column;
5. verifies row manifest/review identity against the payload;
6. reconstructs a `ProposalAuthorizationRecord` and requires its canonical snapshot to match the stored payload exactly.

This detects malformed, drifted, or accidentally tampered persisted evidence before it can be materialized into the 114N registry consumed by later gates.

## Restart and dual-review behavior

`require()` reloads one exact digest-verified decision after process/session restart. `materialize_registry()` rebuilds the in-memory 114N registry only from verified persistent rows, preserving immutable-decision and dual-review semantics. The focused regressions require approved security plus approved operational evidence from distinct reviewers to remain complete after durable reload.

## Migration

`migrations/20260808_calyx_proposal_authorization_decisions.sql` is forward-only and uses `CREATE TABLE IF NOT EXISTS`. It is an implementation artifact only in this slice; no production migration is applied by the PR.

## Permanent boundaries

114P persists review evidence only. It does not create branches, commits, pushes, pull requests, merge or auto-merge PRs, deploy software, publish scientific knowledge, activate taxonomy, mutate the production database as an operator action, or mutate the production Knowledge Graph.

The future bounded Git proposal executor is blocked on durable 114P evidence, executable exact-head validation for 114N/114O/114P, and a separate governance decision granting branch/commit/push/PR proposal authority. Merge and deployment remain separate authorities even after that decision.

## Validation

The dedicated read-only 114P workflow compiles and Ruff-checks the model/store/tests, runs focused 114N plus durable restart/idempotency/tamper/dual-review regressions, asserts the migration contract and non-mutation boundary, and performs diff hygiene.

Canonical repository CI incident #481 currently records hosted jobs terminating before workflow step 1 with `steps=null`. Such attempts are infrastructure evidence only and do not count as executable validation. This slice must remain draft until a real exact-head workflow executes and passes.
