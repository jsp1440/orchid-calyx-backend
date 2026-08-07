# BUILD-MC-200 — Mission Control orchestration portfolio

## Objective

Expose one protected, read-only view of the authoritative autonomous-engineering program state.

## Implemented

- Added `GET /orchestrator/portfolio`.
- Supports owner-scoped `program_id` and architecture text filters.
- Projects program, job, dependency, role, repository, scheduler, lease, receipt, evidence, blocker, and exact-next-action summaries.
- Preserves deterministic ordering.
- Reports the current artifact-registry, review-eligibility, and Brain-capture capabilities without pretending their in-memory reference registries are durable portfolio stores.
- Exposes explicit governance flags showing that merge, deployment, publication, taxonomy activation, and production Knowledge Graph mutation remain disabled.
- Rejects unknown and cross-owner program filters without leaking existence.

## Operational value

Mission Control can now answer what programs exist, what is running, queued, waiting, blocked, completed, which roles and repositories are occupied, what evidence receipts exist, and what exact action is required next.

## Safety

This slice adds no write controls. It cannot claim, execute, complete, merge, deploy, publish, activate taxonomy, access credentials, or mutate production scientific data.
