# CALYX Governed Mutation Journal — Current-Main Recovery Layer

## Mission

Reconstruct the BUILD-BRAIN-114T durable proposal-mutation journal on top of the current-main governed executor candidate in PR #851, preserving its exact reviewed authority model while fixing a recovery limitation in the historical journal lineage.

## Dependency

This branch is stacked on exact PR #851 head `76c5e9763d252c53c7c2e6e7410534924ed155d3` because the journal depends on the current `calyx-git-proposal-mutation-receipt-v3` executor contract. It must not be merged independently ahead of the accepted executor lineage.

## Implemented

- append-only SQLAlchemy journal rows keyed by exact `plan_digest` + monotonically increasing `event_index`;
- durable binding of `patch_program_job_id`, receipt digest, repository, proposal branch, exact base SHA, and reviewed `base_ref`;
- receipt and per-operation evidence digest revalidation on every read;
- row-identity checks and exact replay idempotency;
- divergent replay, event gaps, completed-action regression, and prior-evidence mutation fail closed;
- current receipt schema `calyx-git-proposal-mutation-receipt-v3` and journal event schema `calyx-git-proposal-mutation-journal-event-v3`;
- explicit restart classifications for not-started, resumable partial, failed-before-side-effect, completed subset, and completed states;
- executor journaling after every verified remote operation and before returning/raising terminal evidence;
- executor restart support that loads the latest tamper-checked receipt, verifies plan identity and action prefix, reconstructs the exact created-commit SHA when applicable, and resumes only at the next uncompleted reviewed operation;
- completed retries return the persisted final receipt without re-invoking the remote adapter.

## Recovery correction versus historical 114T-R2

Historical 114T-R2 classified `partial_failure` as resumable while simultaneously treating all failure receipts as journal-terminal, which prevented a later event from advancing the same plan after restart. This reconstruction separates final success states (`completed`, `completed_subset`) from failure observations. A `partial_failure` or pre-side-effect `failed` event remains immutable history but may be followed by a later verified progress event for the same exact plan and unchanged evidence prefix.

This does not claim distributed exactly-once semantics. The live GitHub adapter must independently implement `already_exists_exact` verification for remote idempotency. The journal only prevents CALYX from forgetting or rewriting what it previously verified.

## Governance boundary

This slice adds persistence and restart/recovery semantics only. It does not include or activate:

- a live GitHub credential or transport;
- Git CLI or subprocess execution;
- merge or auto-merge;
- deployment;
- production database migration/application for the journal table;
- scientific publication or Candidate Knowledge promotion;
- taxonomy activation;
- production Knowledge Graph mutation;
- secret disclosure or spending authority.

A production schema migration for the journal remains a separate owner/release operation. Until that exists, hosted validation uses an isolated in-memory database table only.

## Validation contract

Dedicated hosted CI must prove:

- compile and Ruff lint/format;
- adjacent 114R execution-plan and 114S executor regressions;
- journal restart survival;
- exact replay idempotency and divergent-replay rejection;
- base-ref, patch-job, row, receipt, and evidence tamper rejection;
- boolean/gap event-index rejection;
- resumable partial failure after restart;
- failed-before-side-effect retry without history rewrite;
- completed restart performs zero remote operations;
- no merge/deployment/publication/taxonomy/production-data authority;
- no production journal migration is introduced by this PR.

## Next dependency

After this journal layer and PR #851 are accepted, BUILD-BRAIN-114U can implement the narrowly scoped live GitHub mutation adapter authorized by issue #842. That adapter may perform only reviewed proposal operations and must return independently verifiable evidence for branch creation, exact commit creation, proposal-branch push, and one draft pull request. It remains prohibited from merge, deployment, publication, taxonomy, production database/Knowledge Graph mutation, secret disclosure, and spending.
