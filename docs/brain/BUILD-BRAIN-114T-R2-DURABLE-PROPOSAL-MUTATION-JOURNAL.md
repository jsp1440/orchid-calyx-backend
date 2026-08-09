# BUILD-BRAIN-114T-R2 — Durable proposal mutation journal and recovery evidence

## Objective

Persist BUILD-BRAIN-114S-R3 mutation evidence so a worker restart does not erase knowledge of already verified remote side effects.

114T-R2 is an evidence and recovery layer built directly on the exact executable-green 114S-R3 head `5b6e0b49a23383916dfbd9c5e198b970af2d0b92`. It grants no new Git or GitHub operation and does not activate a production transport.

## Append-only journal

`DurableGitProposalMutationJournal` stores ordered events keyed by the exact 114R plan digest. Each row binds the durable `patch_program_job_id`, event index, receipt digest, and complete 114S receipt snapshot.

Every read recomputes the receipt digest, recomputes every operation-evidence digest, verifies row identity, verifies the durable patch-job identity, and reconstructs the typed receipt before returning it.

The journal rejects event gaps, event-index booleans, history regression, changed prior evidence, writes after a terminal event, divergent replay at the same event index, action/evidence ordering mismatch, payload digest mismatch, and row identity mismatch. Identical replay at the same event index is idempotent.

## Executor integration

When a journal capability is injected into `GitProposalMutationExecutor`, the executor records an `in_progress` receipt immediately after each remote operation has returned evidence and that evidence has passed all 114S verification. It records a terminal `completed`, `completed_subset`, `partial_failure`, or `failed` receipt before normal return or the governed mutation error is raised.

Journal persistence is deliberately separate from the mutation adapter. Git/GitHub credentials therefore do not imply database-journal authority, and journal access does not imply Git mutation authority.

If journal persistence fails after a remote side effect, execution stops rather than advancing to another side effect. The system does not claim rollback. Recovery or operator logic must reconcile remote state against the last durable event.

## Recovery classification

`recovery_state()` reconstructs evidence state only:

- `not_started`
- `resumable_partial`
- `completed_subset`
- `completed`
- `failed_before_side_effect`

It binds recovery to the exact plan digest, durable `patch_program_job_id`, repository, proposal branch, and base commit. It identifies the first uncompleted action from the exact dependency-closed 114R plan prefix but does not execute that action.

A partial failure is terminal for that journaled execution attempt but classified as `resumable_partial` because a subsequent recovery controller may reconcile and re-authorize continuation. This slice does not automatically resume a failed attempt.

## Exactly-once limitation

114T-R2 does not claim distributed exactly-once semantics. GitHub side effects and database persistence are separate systems. A process may die after a remote side effect succeeds but before its journal event commits.

The design instead provides auditable recovery with strict evidence continuity. Remote `already_exists_exact` results remain acceptable only when the 114S mutation adapter proves that the existing remote state exactly matches the authorized operation. No rollback claim is made for verified remote effects.

## Database activation boundary

The SQLAlchemy model defines `calyx_git_proposal_mutation_journal`, including durable patch-job identity. This implementation does **not** create, apply, or activate a production Alembic migration. Focused tests create only the isolated table in SQLite.

Production schema activation remains a separate operations/governance action requiring its own validated migration and release decision.

## Permanent prohibitions

114T-R2 adds no merge or auto-merge capability, deployment capability, scientific publication authority, taxonomy activation, production scientific-data mutation, production Knowledge Graph mutation, live GitHub credential transport, or owner private signing key.
