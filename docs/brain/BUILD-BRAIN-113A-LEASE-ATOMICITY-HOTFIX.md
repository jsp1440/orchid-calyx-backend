# BUILD-BRAIN-113A — Lease atomicity hotfix

## Context

PR #508 merged the deterministic dry-run execution loop before two P1 review findings were incorporated.

## Corrective implementation

- Reject expired leases before deterministic execution begins.
- Reject expired leases during heartbeat and completion.
- Reserve completion atomically with a conditional status transition from `running` to `completing` that verifies the job has no outcome, the worker and token match, and the lease remains unexpired.
- Roll back the reservation on downstream completion errors.
- Add regression coverage proving expired leases cannot execute or complete work.

## Governance and safety

The correction grants no shell, network, provider, merge, deployment, publication, credential, taxonomy, or production Knowledge Graph authority. It closes a stale-worker race in the bounded internal executor.

## Required validation

Compile, Ruff, focused dry-run and worker tests, and baseline repository validation must pass before merge.
