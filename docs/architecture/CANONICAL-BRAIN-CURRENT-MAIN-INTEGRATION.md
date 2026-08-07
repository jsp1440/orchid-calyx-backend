# Canonical Brain — Current Main Integration

## Purpose

Rebuild the validated Canonical Brain surface directly on current `main` so it integrates with the repository's newer Calyx orchestration runtime without replaying stale stacked ancestry.

## Why this replacement was required

The earlier stabilization slices were individually validated, but `main` continued advancing and added authoritative Calyx runtime components including governed assignment, dry-run execution, artifact registration, review eligibility, Brain candidate capture, Mission Control portfolio infrastructure, and an authoritative-executor boundary. Extending the old stack would have required copying newer runtime modules backward and would have created parallel or stale implementations.

This integration therefore transfers the validated Canonical Brain surface onto current `main` and uses the current Calyx runtime as the authoritative execution/evidence layer. The initial transfer was applied atomically as a single Git tree/commit so file identity was preserved without replaying stale branch history.

## Canonical Brain responsibilities

- canonical architecture, intent, decision, relationship, and search registry;
- deterministic snapshots and candidate persistence;
- constitutional build-admission rules;
- governed build queue and deterministic assignment records;
- non-authoritative preflight boundary;
- leases, heartbeat, timeout classification, bounded recovery candidates, and cancellation receipts;
- bridge from governed queue state to the existing Calyx dependency scheduler;
- bridge from completed authoritative Canonical Brain receipts to existing Calyx artifact, review, and Brain candidate-capture contracts.

## Existing Calyx responsibilities reused

Canonical Brain does not duplicate the following current-main components:

- `app/calyx_orchestrator/scheduler.py` — dependency, critical-path, and capacity scheduling;
- `app/calyx_orchestrator/executor.py` — capability enforcement, deterministic preflight receipts, and executor contracts;
- `app/calyx_orchestrator/dry_run_service.py` — release-after-preflight semantics so dry runs cannot complete real jobs;
- `app/calyx_orchestrator/artifact_registry.py` — immutable artifact provenance, checksum, evidence, and lineage;
- `app/calyx_orchestrator/review_eligibility.py` — review classes, self-approval prevention, and release eligibility;
- `app/calyx_orchestrator/brain_capture.py` — reviewed evidence-backed candidate Brain capture;
- current Calyx assignment, authoritative-executor, and Mission Control portfolio infrastructure.

## Non-authoritative preflight correction

Current `main` explicitly distinguishes deterministic dry-run validation from authoritative execution. The inherited Canonical Brain adapter previously returned a Canonical `completed` receipt from a dry run. That path is removed in this integration.

`app/canonical_brain/executor.py` now wraps the current Calyx deterministic executor and returns an `ExecutionResult` with `dry_run=true` and `authoritative=false`. It does not create a Canonical completion receipt. A real completion still requires a separate authoritative execution/evidence path.

## Safety boundaries

- autonomous merge, deployment, publication, credential access, and production Knowledge Graph mutation remain prohibited;
- deterministic preflight cannot complete a real job;
- completed execution receipts require evidence URI(s) and checksums before evidence packaging;
- review requester and producer must be distinct;
- candidate capture remains unpublished and subject to the existing Calyx review gates;
- scheduler and evidence bridges are projections/translation boundaries, not new authorities.

## Validation lineage

Earlier clean slices established passing compile, Ruff, and focused pytest evidence for the registry, governance, queue/orchestration, executor/lease, and scheduler-bridge layers. The current-main integration must pass the complete `tests/test_canonical_brain_*.py` suite against the latest repository before it supersedes those drafts.

At the current GitHub head, Actions is creating workflow runs but terminating them before any job step is instantiated, including the unrelated legacy BUILD-088E workflow. That state is recorded as an external validation-execution blocker rather than a passing or failing code result.
