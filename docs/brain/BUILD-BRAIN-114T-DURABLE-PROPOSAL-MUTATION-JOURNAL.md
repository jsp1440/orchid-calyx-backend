# BUILD-BRAIN-114T — Durable proposal mutation journal and recovery evidence

## Objective

Persist BUILD-BRAIN-114S mutation evidence so a worker restart does not erase knowledge of already verified remote side effects.

114T is an evidence/recovery layer. It grants no new Git or GitHub operation and does not activate a production transport.

## Append-only journal

`DurableGitProposalMutationJournal` stores ordered events keyed by the exact 114R plan digest. Each event contains the complete 114S receipt snapshot and its receipt digest. Reads recompute the receipt digest, recompute every operation-evidence digest, and compare row identity fields before reconstructing a receipt.

The journal rejects event gaps, history regression, writes after a terminal event, divergent replay at the same event index, action/evidence ordering mismatch, and payload/row digest mismatch. An identical replay at the same index is idempotent.

## Executor integration

When a journal capability is injected into `GitProposalMutationExecutor`, the executor records an `in_progress` receipt immediately after each remote operation has returned evidence and that evidence has passed 114S verification. It records a terminal `completed`, `completed_subset`, `partial_failure`, or `failed` receipt before returning or raising.

Journal persistence is deliberately separate from the mutation adapter. A live Git/GitHub credential therefore does not imply database-journal authority and journal access does not imply Git mutation authority.

If journal persistence fails after a remote side effect, execution stops rather than advancing to another side effect. The raised state cannot truthfully claim rollback; operator/recovery logic must reconcile the remote state against the last durable event.

## Dependency-closed mutation and recovery

A safety review found that merely sorting authorized actions into canonical order was not sufficient. Sparse action sets could otherwise omit a required predecessor, for example attempting to open a pull request without a verified create-commit step in the same authorization chain.

BUILD-BRAIN-114R and BUILD-BRAIN-114S now require every executable action set to be a non-empty dependency-closed prefix of:

1. `create_branch`
2. `create_commit`
3. `push_branch`
4. `open_pull_request`

114S also requires push and PR evidence to reference the exact commit SHA obtained from the verified create-commit operation; the continuity check can no longer be skipped because a commit SHA was absent. 114T recovery therefore reconstructs only prefixes that the mutation executor itself can safely prove.

## Recovery classification

`recovery_state()` reconstructs only evidence state:

- `not_started`
- `resumable_partial`
- `completed_subset`
- `completed`
- `failed_before_side_effect`

It identifies the next action from the exact 114R plan prefix but does not execute it. Resume execution remains subject to fresh 114O/114Q authorization verification, dependency closure, remote-state reconciliation, and 114S evidence checks.

## Exactly-once limitation

114T does not claim distributed exactly-once semantics. GitHub side effects and database persistence are separate systems. The design instead provides auditable at-least-once recovery with strict idempotency evidence: remote `already_exists_exact` state is acceptable only when the live adapter proves it matches the authorized operation exactly.

This distinction is important after a process dies between a successful remote operation and journal commit.

## Database activation boundary

The SQLAlchemy model defines `calyx_git_proposal_mutation_journal`, but this slice does not activate or run a production Alembic migration. Production schema activation must be performed as a separately validated migration operation after hosted CI is restored. Tests create only the focused table in an isolated SQLite database.

## Permanent prohibitions

114T does not add merge/auto-merge, deployment, publication, taxonomy activation, production scientific-data mutation, or production Knowledge Graph mutation authority. It also does not wire a production GitHub token or private owner key.

Canonical hosted-runner incident #481 remains the executable-validation blocker. The dedicated 114T workflow now includes the dependency-closure regression, but no merge or production activation is appropriate while exact-head workflow jobs terminate before step 1 with `steps=null`.
