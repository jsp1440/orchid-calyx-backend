# Slice 4 — Canonical Brain to Calyx Scheduler Bridge

## Status

Candidate integration slice stacked on validated Slice 3R. Not merged or deployed.

## Decision

Do not create a second dependency scheduler inside the Canonical Brain. The repository already contains `app/calyx_orchestrator/scheduler.py`, a deterministic scheduler with dependency, critical-path, concurrency, repository, role, architecture, and mutating-branch guards.

The Canonical Brain supplies constitutional admission and governed queue state. This slice adds a narrow fail-closed adapter into the existing scheduler.

## Bridge behavior

- Every governed queue item requires explicit scheduler metadata.
- Missing metadata fails closed.
- Metadata for a build absent from the governed queue fails closed.
- Duplicate metadata identities fail closed.
- `architecture:<name>` identifiers normalize to the existing scheduler architecture key.
- Brain queue priorities are preserved.
- Queue lifecycle maps to scheduler lifecycle:
  - admitted -> waiting
  - blocked -> blocked / BLOCKED
  - scheduled -> queued
  - running -> running
  - completed -> completed / DELIVERED
  - cancelled -> cancelled / CANCELLED
- Existing dependency and critical-path behavior remains authoritative.
- Existing repository/role/architecture/global concurrency limits remain authoritative.
- Existing mutating-branch serialization remains authoritative.

## Safety

The bridge is a pure projection. It does not transition the governed queue, assign an agent, execute code, acquire credentials, launch workers, merge, deploy, publish, write production data, or mutate the production Knowledge Graph.

## Validation

Focused tests cover constitutional blocking, lifecycle mapping, prerequisite release, mutating-branch serialization, missing/orphaned metadata rejection, and architecture-key normalization. The complete Canonical Brain focused suite must pass compile, Ruff, and pytest before this slice is accepted.
