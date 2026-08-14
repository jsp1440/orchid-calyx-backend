# BUILD-BRAIN-114U — Mission Control Proposal Execution Evidence

**Status:** read-only current-main implementation candidate; no credential or mutation activation.

## Purpose

Complete the owner-visible Mission Control portion of BUILD-BRAIN-114U without widening CALYX authority. The existing proposal-executor status surface reports policy/readiness. This slice adds durable operation evidence from the append-only Git proposal mutation journal so Mission Control can distinguish policy readiness from actual proposal execution progress.

## Read-only execution contract

`proposal_execution_mission_control_status(db)` reads at most the 25 most recently touched proposal plans and revalidates each selected plan through `DurableGitProposalMutationJournal.latest(...)`, preserving the journal's tamper/gap/action-order checks.

For each durable proposal receipt it exposes only non-secret provenance already present in governed evidence:

- plan digest;
- patch-program job id;
- repository;
- reviewed base ref and exact base commit SHA;
- confined proposal branch;
- receipt status and digest;
- completed remote actions;
- next/current remote operation;
- verified created commit SHA when present;
- draft PR number/URL/draft marker when present;
- failure code and terminal state.

If the durable journal table is absent, unreadable, malformed, or fails tamper validation, the status read fails closed with no inferred execution state. The read performs no remote GitHub call and no repository, database, deployment, publication, taxonomy, or Knowledge Graph mutation.

## Route integration

The authenticated `/api/mission-control/briefing/proposal-executor` feed now returns two distinct truth surfaces:

- `proposal_executor`: feature-policy / credential-readiness boundary;
- `proposal_execution`: durable remote-operation evidence and active/latest execution state.

This separation prevents an enabled policy from being confused with a completed remote operation, and prevents recorded side effects from being confused with new authority.

## Governance boundary

This implementation does not enable the proposal executor, configure credentials, create branches/commits/pushes/PRs, merge, deploy, apply migrations, publish science, activate taxonomy, mutate production DB/KG state, disclose secrets, or spend funds.

Live credential registration and runtime mutation activation remain owner-governed. Merge of this implementation remains behind the owner merge gate.
