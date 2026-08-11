# CALYX Governed Mutation Executor — Current-Main Recovery

## Objective

Recover the validated bounded proposal-mutation executor from historical BUILD-BRAIN-114S-R4 onto current canonical `main` without widening authority or reviving the stale historical PR branch.

## Base

This recovery starts from canonical backend `main` commit `bc6ab47a4f99984e11deac2d07bf675944b63416` (2026-08-11) and ports only the executor, focused regression coverage, this record, and a read-only validation workflow.

Historical PR `#817` remains source material. It should not be merged independently after a current-main successor is validated.

## Capability

The executor consumes an exact evidence-bound `GitProposalExecutionPlan` and delegates proposal-only side effects to an injected `GitProposalMutationAdapter`.

Allowed dependency-closed operations are limited to:

1. create proposal branch;
2. create exact evidence-bound commit;
3. push that exact commit to the proposal branch;
4. open a pull request against the reviewed base ref and exact base commit.

The executor:

- reconstructs and compares the authorized plan before any mutation;
- requires a repository allowlist and `autonomy/proposal/` branch namespace;
- re-verifies the owner grant immediately before every adapter side effect;
- binds the reviewed `base_ref` and `base_commit_sha` into PR evidence;
- verifies commit/push/PR postconditions against the exact plan;
- returns evidence-bearing success or partial-failure receipts;
- preserves structured exception codes or exact failure messages.

Receipt schema remains `calyx-git-proposal-mutation-receipt-v3` because this recovery intentionally preserves the reviewed R4 evidence contract rather than inventing a new authority model.

## Validation contract

Focused regressions cover:

- successful branch → commit → push → PR flow;
- dependency-closed action order;
- owner-grant expiry between side effects;
- wrong pushed commit rejection;
- exact remote failure evidence;
- reviewed base-ref mismatch rejection;
- strict positive non-boolean pull-request-number validation.

Dedicated CI also compiles and Ruff-checks the executor, runs the merged execution-plan regressions, statically enforces the authority boundary, and checks diff hygiene.

## Permanent authority boundary

This implementation contains only an injected adapter protocol. It does **not** contain or activate:

- GitHub credentials or a live network transport;
- unrestricted Git CLI or subprocess execution;
- merge or auto-merge;
- deployment;
- scientific publication or Candidate Knowledge promotion;
- taxonomy activation;
- production database mutation;
- production Knowledge Graph mutation;
- secrets or spending authority.

A live scoped GitHub transport remains a separate implementation and governance layer. Merge of this executor core is an owner/release decision.
