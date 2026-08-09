# BUILD-BRAIN-114S — Current-parent bounded Git proposal mutation executor

## Objective

Rebuild the bounded proposal-mutation executor on the authoritative BUILD-BRAIN-114R v2 lineage rather than the superseded historical 114R branch.

## Provenance binding

The executor accepts only a `calyx-git-proposal-execution-plan-v2` produced from the durable authorization chain. Immediately before mutation it rebuilds 114R from the exact manifest, durable review store, 114O request, and externally verified 114Q owner grant and requires exact plan equality.

The durable `patch_program_job_id` is carried through the plan, mutation receipt, create-commit operation, and returned commit evidence. A commit response with a different patch job fails closed.

## Dependency closure and commit continuity

A static audit found two related hazards in the superseded 114S lineage: sparse action subsets could skip prerequisites, and push/PR continuity checks were conditional when no create-commit SHA had been observed. The authoritative rebuild closes both gaps.

Executable actions must be a non-empty prefix of `create_branch -> create_commit -> push_branch -> open_pull_request`. BUILD-BRAIN-114R v2 enforces prerequisite closure at planning time and 114S independently enforces the exact prefix immediately before mutation.

Push evidence must equal the exact verified create-commit SHA. Pull-request evidence must identify the exact authorized head/base and the same verified commit SHA. Missing commit continuity is a failure, not a reason to skip verification.

## Side-effect boundary

The executor receives a narrow injected adapter and loads no token, credential, private owner key, subprocess, Git CLI, or HTTP client itself. The adapter protocol exposes no merge, auto-merge, deployment, publication, taxonomy, production database, or Knowledge Graph mutation method.

Remote partial failures are not represented as rollback. The executor raises a receipt containing only side effects whose evidence was verified before failure.

## Validation state

Focused tests cover the current durable patch-job lineage, full branch/commit/push/PR flow, dependency closure, wrong pushed commit rejection, and partial-failure evidence. The dedicated workflow runs the corrected 114R regression suite and 114S regressions together.

Canonical hosted-runner incident #481 remains the executable-validation blocker. No live GitHub adapter, credential activation, merge, deployment, publication, taxonomy activation, production DB mutation, or production KG mutation is authorized while exact-head jobs terminate before step 1.
