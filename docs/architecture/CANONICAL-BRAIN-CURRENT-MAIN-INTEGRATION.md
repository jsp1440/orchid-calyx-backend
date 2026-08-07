# Canonical Brain — Current Main Integration

## Purpose

Rebuild the validated Canonical Brain surface directly on current `main` so it integrates with the repository's newer Calyx orchestration runtime without replaying stale stacked ancestry.

## Why this replacement was required

The earlier stabilization slices were individually validated, but `main` continued advancing and added authoritative Calyx runtime components including governed assignment, dry-run execution, artifact registration, review eligibility, Brain candidate capture, and Mission Control portfolio infrastructure. Extending the old stack would have required copying newer runtime modules backward and would have created parallel or stale implementations.

This integration therefore transfers the already validated Canonical Brain files byte-for-byte onto current `main` and uses the current Calyx runtime as the authoritative execution/evidence layer. The initial transfer was applied atomically as a single Git tree/commit so file identity was preserved without replaying stale branch history.

## Canonical Brain responsibilities

- canonical architecture, intent, decision, relationship, and search registry;
- deterministic snapshots and candidate persistence;
- constitutional build-admission rules;
- governed build queue and deterministic assignment records;
- candidate-only dry-run executor boundary;
- leases, heartbeat, timeout classification, bounded recovery candidates, and cancellation receipts;
- bridge from governed queue state to the existing Calyx dependency scheduler;
- bridge from completed Canonical Brain receipts to existing Calyx artifact, review, and Brain candidate-capture contracts.

## Existing Calyx responsibilities reused

Canonical Brain does not duplicate the following current-main components:

- `app/calyx_orchestrator/scheduler.py` — dependency, critical-path, and capacity scheduling;
- `app/calyx_orchestrator/artifact_registry.py` — immutable artifact provenance, checksum, evidence, and lineage;
- `app/calyx_orchestrator/review_eligibility.py` — review classes, self-approval prevention, and release eligibility;
- `app/calyx_orchestrator/brain_capture.py` — reviewed evidence-backed candidate Brain capture;
- current Calyx assignment, execution, and Mission Control portfolio infrastructure.

## Safety boundaries

- autonomous merge, deployment, publication, credential access, and production Knowledge Graph mutation remain prohibited;
- completed execution receipts require evidence URI(s) and checksums before evidence packaging;
- review requester and producer must be distinct;
- candidate capture remains unpublished and subject to the existing Calyx review gates;
- scheduler and evidence bridges are projections/translation boundaries, not new authorities.

## Validation lineage

Earlier clean slices established passing compile, Ruff, and focused pytest evidence for the registry, governance, queue/orchestration, executor/lease, and scheduler-bridge layers. The current-main integration must pass the same complete `tests/test_canonical_brain_*.py` suite against the latest repository before it supersedes those drafts.
