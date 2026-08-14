# BUILD-BRAIN-114U — Mission Control Proposal Execution Evidence

**Status:** read-only current-main implementation candidate; no credential or mutation activation.

## Purpose

Complete the owner-visible Mission Control portion of BUILD-BRAIN-114U without widening CALYX authority. The existing proposal-executor status surface reports policy/readiness. This slice adds durable operation evidence from the append-only Git proposal mutation journal so Mission Control can distinguish policy readiness from actual proposal execution progress.

## Read-only execution contract

`proposal_execution_mission_control_status(db)` is a bounded, read-only status projection over durable proposal execution evidence. It returns the 25 most recently touched proposal plans and independently scans at most 100 latest per-plan checkpoints when determining whether an older active/resumable execution exists.

The status path does **not** call `DurableGitProposalMutationJournal.latest(...)` for every selected plan, because that recovery method intentionally validates the entire event history and therefore has unbounded read cost as a journal grows. Instead, Mission Control selects only the latest event row for each scanned plan, verifies aggregate event-index continuity (`max(event_index) == count(events)`), and validates the selected cumulative receipt through `validate_checkpoint_receipt(...)`. The latest receipt contains the complete completed-action/evidence prefix plus a canonical receipt digest. Full-history transition validation remains unchanged for executor recovery and mutation paths.

If more than 100 plans exist and no active plan is found inside the bounded scan, Mission Control reports `active_execution_known=false` with `active_execution_state=unknown_beyond_bounded_scan`; it never reports a false "none" merely because the active plan fell outside the recent-history window.

For each durable proposal receipt it exposes only non-secret provenance already present in governed evidence:

- plan digest;
- patch-program job id;
- repository;
- reviewed base ref and exact base commit SHA;
- confined proposal branch;
- receipt status and digest;
- completed remote actions;
- current remote operation **only when the durable receipt proves that operation was inside the authorized plan**;
- current-operation evidence state;
- verified created commit SHA when present;
- draft PR number/URL/draft marker when present;
- failure code and terminal state.

### Authorized-plan boundary

An `in_progress` receipt is written after each successful action. At that instant Calyx cannot infer from the global action order whether the action was the final member of an owner-approved dependency-closed subset plan or whether another action was authorized. Therefore Mission Control returns `current_remote_operation=null` and `current_remote_operation_state=authorization_boundary_unknown` for that state rather than inventing authority.

A `partial_failure` or `failed` receipt is different: it exists only because the executor entered the next operation in the reviewed plan and that attempt failed. In that case the next prefix action is provably authorized and may be reported with `current_remote_operation_state=authorized_by_failed_attempt`.

Terminal `completed` / `completed_subset` receipts report no current remote operation.

If the durable journal table is absent, unreadable, malformed, has an event-index continuity failure, or fails latest-checkpoint tamper validation, the status read fails closed with no inferred execution state. The read performs no remote GitHub call and no repository, database, deployment, publication, taxonomy, or Knowledge Graph mutation.

## Route integration

The authenticated `/api/mission-control/briefing/proposal-executor` feed returns two distinct truth surfaces:

- `proposal_executor`: feature-policy / credential-readiness boundary;
- `proposal_execution`: bounded durable remote-operation evidence and active/latest execution state.

This separation prevents an enabled policy from being confused with a completed remote operation, prevents recorded side effects from being confused with new authority, and prevents bounded observability from silently becoming an unbounded production read.

## Review-finding closure

The current implementation closes the three review findings raised against the initial 114U status slice:

1. next action is never derived from the global action order when the owner-approved subset boundary is unknown;
2. active execution is searched independently of the 25-item recent-history display and is explicitly unknown if the bounded scan is exhausted;
3. Mission Control validates cumulative latest checkpoints rather than loading every historical event for every displayed plan.

Regression coverage includes subset-boundary ambiguity, failed-attempt authorization evidence, active execution outside the recent-history window, bounded-scan exhaustion, and event-index gap detection.

## Governance boundary

This implementation does not enable the proposal executor, configure credentials, create branches/commits/pushes/PRs, merge, deploy, apply migrations, publish science, activate taxonomy, mutate production DB/KG state, disclose secrets, or spend funds.

Live credential registration and runtime mutation activation remain owner-governed. Merge of this implementation remains behind the owner merge gate.
