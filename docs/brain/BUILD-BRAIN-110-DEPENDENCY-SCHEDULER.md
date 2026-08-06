# BUILD-BRAIN-110 — Dependency-aware scheduler

## Status

Candidate implementation delivered on a stacked branch. No merge, deployment, publication, credential access, or production Knowledge Graph mutation occurred.

## Decision

Add a pure deterministic scheduler projection before changing the durable claim path. This allows dependency and capacity policy to be validated independently from database locking and worker execution.

## Implemented behavior

- validates dependency identities and rejects missing, self, and cyclic edges;
- distinguishes waiting prerequisites from failed prerequisites;
- releases only jobs whose predecessors reached `DELIVERED` or `NO_OP`;
- computes critical-path depth from downstream dependency length;
- orders candidates by critical-path depth, explicit priority, creation order, and stable job key;
- enforces global, architecture, role, and repository running limits;
- reports exact non-runnable codes and `blocked_by` job keys;
- emits a stable read-only scheduler snapshot and runnable order;
- does not claim jobs, mutate leases, execute code, merge, deploy, publish, or alter production data.

## Validation scope

Focused tests cover deterministic ordering under reversed input order, prerequisite waiting versus failure, successful dependency release, capacity ordering, architecture/role/repository limits, and invalid dependency graphs. The focused workflow validates BUILD-BRAIN-108 through BUILD-BRAIN-110 together.

## Next integration

The next bounded slice should adapt persisted `CalyxProgramJob` and `CalyxProgramDependency` rows into this scheduler projection and expose the snapshot through protected Mission Control. Atomic worker claiming remains governed by the existing admission and lease code.
