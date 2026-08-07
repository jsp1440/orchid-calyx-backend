# Slice 3R — Governed Queue, Orchestration, Executor, Leases, and Recovery

## Status

Candidate implementation rebuilt on the validated Slice 2R branch. Draft-only; not merged or deployed.

## Purpose

Connect constitutional build admission to a deterministic, auditable execution boundary without granting autonomous merge, deployment, publication, shell execution, credential handling, or production Knowledge Graph mutation.

## Implemented components

### Governed build queue

- Constitution evaluation occurs before queue admission.
- Compliant work enters `admitted`; violations enter `blocked`.
- Blocked work remains visible but cannot be scheduled.
- Allowed lifecycle: `admitted -> scheduled -> running -> completed` with cancellation from active states.
- Repeated identical submissions are idempotent; conflicting durable identities fail closed.

### Governed agent assignment

- Only `admitted` builds may be assigned.
- Agents must be enabled and declare support for the build architecture.
- Matching agents are ordered deterministically by stable agent ID.
- Assignment IDs are deterministic hashes of build, agent, and architecture identities.

### Execution receipts

- Start receipts require a scheduled assignment and move queue state to `running`.
- Completion requires a running assignment, at least one evidence URI, and an output checksum.
- Receipt IDs are deterministic and conflicting receipt reuse fails closed.

### Dry-run executor boundary

- Provider-neutral executor protocol.
- Current adapter is deterministic dry-run only.
- Unsupported capabilities fail closed.
- Scheduled-but-not-running assignments cannot execute.
- Inputs and outputs receive deterministic SHA-256 checksums.
- Evidence URIs are normalized and deduplicated.
- No shell, network, deployment, merge, publication, or production mutation capability is implemented.

### Execution leases and recovery

- One active worker lease per assignment.
- Same-worker acquisition is idempotent while the lease is active.
- Heartbeats require lease ownership and extend expiry.
- Naive timestamps fail closed; lease times normalize to UTC.
- Expired work yields a `retry_candidate` only while bounded attempts remain.
- Attempt exhaustion yields `manual_review`.
- Cancellation creates a deterministic receipt and does not launch replacement work.

## Validation gate

Authoritative GitHub Actions must pass:

- Python compile for `app/canonical_brain`;
- Ruff for canonical Brain code and focused tests;
- all `tests/test_canonical_brain_*.py` focused tests.

Any failure is corrected before additional architecture expansion.

## Safety boundary

This slice does not launch agents, execute arbitrary code, call external services, read credentials, merge code, deploy services, publish scientific outputs, write production databases, or mutate the production Knowledge Graph.
