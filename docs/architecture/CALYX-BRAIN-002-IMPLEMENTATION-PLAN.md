# CALYX-BRAIN-002 — Reasoning Ledger and Memory Contracts

## Status

Operational implementation for Issue #142. The deterministic in-memory kernel is
retained as the domain reference implementation; authenticated production paths
use the revisioned SQLAlchemy repository described below.

## Implemented architecture

- `reasoning_ledger.ledger_heads` provides one row-locked current-version pointer
  per deterministic ledger identity.
- `reasoning_ledger.ledger_revisions` stores every immutable canonical payload and
  SHA-256 payload hash. No revision is updated or deleted by application code.
- `reasoning_ledger.audit_events` records the authenticated actor, operation,
  version, project, and governance details for every mutation.
- Mutations require `expected_version`, lock the head row, insert one revision and
  one audit event, advance the head, and commit as one transaction.
- Research Station project existence, ownership, and archive state are validated
  against `research_station.projects`; project data is not duplicated.
- Literature provenance is resolved through the existing output-bundle and source-
  binding repositories. Resolved paper, claim, evidence, extraction-run, and hash
  references are validated; explicitly unresolved references remain unresolved.
- The API derives owner, entry author, reviewer, and audit actor from
  `verify_owner_or_api_key`. Request bodies cannot set those identities.
- Review approval is bound to both the resulting ledger version and its exact
  ledger fingerprint. Any later append or conflict resolution makes it stale.
- No route publishes to the Knowledge Graph. Validation only reports explicit
  governance blockers.

## API

- `POST /api/reasoning-ledgers`
- `POST /api/reasoning-ledgers/{ledger_id}/entries`
- `GET /api/reasoning-ledgers/{ledger_id}`
- `GET /api/reasoning-ledgers/{ledger_id}/history`
- `POST /api/reasoning-ledgers/{ledger_id}/validate`
- `POST /api/reasoning-ledgers/{ledger_id}/conflicts/{conflict_id}/resolve`
- `POST /api/reasoning-ledgers/{ledger_id}/reviews`
- `GET /api/research/projects/{project_id}/reasoning-ledgers`

## Migration

`migrations/103_reasoning_ledger.sql` is additive and idempotent. It depends on
the existing Research Station migration and adds foreign keys to canonical project
IDs. `migrations/103_reasoning_ledger_rollback.sql` is provided solely for
disposable validation and pre-production rollback; production history must not be
dropped casually.

## Chain-of-thought boundary

Private model chain-of-thought is neither accepted nor stored. API schemas forbid
unknown fields and recursively reject private-reasoning keys inside extensible
metadata. Stored text is limited to externally reviewable objectives, evidence,
operations, assumptions, conflicts, conclusions, and concise rationales.

## Deployment prerequisites

Apply migration 101 before migration 103, configure the existing database and
authentication environment, and run the dedicated `CALYX-BRAIN-002 Validation`
workflow. No production migration or deployment is performed by this PR.

## Validation record

Local focused reasoning/API tests: 39 passed, with the PostgreSQL-only migration
test skipped because Docker and `psql` are not installed locally. Adjacent Research
Station and Literature Intelligence tests: 15 passed. Ruff, Ruff formatting,
compile/import smoke, secret-pattern scan, and repository hygiene passed.

GitHub Actions workflow `CALYX-BRAIN-002 Validation` run `30414420839` passed,
including disposable PostgreSQL 16 migration apply, idempotent reapply, schema
verification, and rollback.

## Objective

Implement the first governed Calyx reasoning-ledger kernel on top of the merged Literature Intelligence and Research Station foundations.

## Required scope

- Versioned contracts for objectives, plans, ordered steps, evidence selections, assumptions, hypotheses, conflicts, operations, artifacts, validation results, conclusions, review decisions, memory references, audit events, and module definitions.
- Deterministic logical identities and canonical serialization that exclude runtime timestamps from identity.
- Append-only or revisioned persistence with complete history and audit events.
- Provenance links to literature paper, claim, and evidence IDs; concepts; datasets; methods; tools; executions; output hashes; and Research Station project IDs.
- First-class uncertainty, counterevidence, unresolved assumptions, unresolved conflicts, validation failures, confidence, and concise rationale summaries.
- Human review gates before canonical publication or irreversible actions.
- Tenant and project isolation with authenticated create, append, retrieve-current, retrieve-history, validate, and review-decision APIs.
- Explicit prohibition on storing private model chain-of-thought.

## Acceptance path

`literature evidence -> reasoning objective -> evidence/counterevidence -> assumptions/conflicts -> conclusion -> review gate -> governed retrieval`

The acceptance test must prove deterministic serialization, provenance integrity, blocked publication below threshold or with unresolved conflicts, complete revision/audit retrieval, and cross-tenant/cross-project denial.

## Boundaries

Do not implement Data Intelligence, autonomous agents, marketing or outreach workflows, automatic Knowledge Graph publication, deployment, or unrelated CI repairs in this build.

## Validation

Run focused unit and integration tests, tenant/project isolation tests, deterministic repeated-run tests, Ruff, formatting, import smoke tests, configured type checks, secret scanning, and disposable PostgreSQL migration validation if a migration is added.
