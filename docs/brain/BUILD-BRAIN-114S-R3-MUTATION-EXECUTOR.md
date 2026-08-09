# BUILD-BRAIN-114S-R3 — Bounded Git proposal mutation executor

## Objective

Implement the bounded proposal-mutation executor directly on the executable-green BUILD-BRAIN-114R-R5 chain without changing Brain schemas or granting merge/deployment/scientific publication authority.

## Parent lineage

Exact parent: BUILD-BRAIN-114R-R5 PR #785 head `25c0b731b9055178bccfd4f556387915c528f57f`.

Inherited trust chain:
`114M-R3 #772 → 114N-R6 #781 → 114P-R5 #782 → 114O-R5 #783 → 114Q-R5 #784 → 114R-R5 #785 → 114S-R3`.

Every parent layer has executable CI evidence on its exact code head before this slice was created.

## Execution contract

Immediately before any adapter side effect, the executor rebuilds the exact 114R plan from the manifest, durable review store, authorization request, and externally verified owner grant. Exact plan equality is required.

The executor permits only a non-empty dependency-closed prefix of:
`create_branch → create_commit → push_branch → open_pull_request`.

It enforces:
- explicit repository allowlist;
- `autonomy/proposal/*` branch namespace;
- exact base commit binding;
- exact durable `patch_program_job_id` through request, plan, receipt, create-commit parameters, and returned commit evidence;
- exact postimage hashes in commit evidence;
- pushed commit SHA must equal the verified created commit SHA;
- PR head commit SHA must equal that same commit SHA;
- PR number must be a positive exact `int`, never a boolean;
- `already_exists_exact` is the only accepted idempotent pre-existing state.

Partial remote failures are represented by deterministic receipts containing only side effects whose returned evidence was verified before the failure. No rollback is claimed.

## Authority boundary

The core executor contains no Git CLI, subprocess, GitHub token, HTTP client, owner private key, merge API, auto-merge capability, deployment client, publication client, taxonomy activation path, production database mutation path, or production Knowledge Graph mutation path.

A narrow `GitProposalMutationAdapter` is injected by a future trusted transport boundary. This slice does not wire live GitHub credentials or activate production transport.

## Validation

Dedicated CI compiles and lints the 114R/114S surfaces, runs focused plan and mutation regressions, statically checks the authority boundary, and runs diff hygiene. Regression coverage includes successful branch/commit/push/PR evidence, dependency closure, wrong pushed commit, strict PR number typing, and partial remote failure receipts.

## Governance

This implementation is within the previously approved bounded proposal-mutation scope only. Merge/auto-merge, deployment, scientific publication, taxonomy activation, production DB mutation, and production Knowledge Graph mutation remain prohibited. Live credential/transport activation remains a separate operations/governance decision.
