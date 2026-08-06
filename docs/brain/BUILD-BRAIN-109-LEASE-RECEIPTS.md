# BUILD-BRAIN-109 — Execution leases and recovery receipts

## Status

Candidate implementation delivered on a stacked branch. No merge, deployment, publication, credential access, or production Knowledge Graph mutation occurred.

## Decision

Reuse the existing durable `CalyxProgramJob` lease fields and `PersistentProgramWorker` instead of introducing a second lease system. Add a narrow bridge that accepts only independently verifiable `ExecutionReceipt` objects from BUILD-BRAIN-108.

## Implemented contracts

- receipt identity must match program ID, program job ID, and job key;
- receipt checksum and state/outcome consistency are verified before completion;
- successful receipts complete the durable lease and release eligible downstream jobs;
- blocked and timed-out receipts persist blocker codes and exact human actions;
- cancellation requires a non-empty reason and persists an explicit cancellation receipt;
- stale worker IDs or lease tokens fail closed;
- duplicate cancellation/completion replay is rejected after the lease is consumed;
- receipt evidence remains candidate operational evidence and does not authorize merge, deployment, publication, or graph mutation.

## Validation scope

Focused tests cover delivered receipt completion, dependency release, receipt identity mismatch, cancellation receipt persistence, stale replay rejection, and timeout classification. The BUILD-BRAIN-108 workflow was expanded to install project dependencies and validate BUILD-BRAIN-108 and BUILD-BRAIN-109 together.

## Dependencies and next work

BUILD-BRAIN-110 may consume terminal receipt outcomes and durable dependency states to compute deterministic runnable order and critical-path projections. Production activation remains gated by review, merge, migration, and deployment policy.
