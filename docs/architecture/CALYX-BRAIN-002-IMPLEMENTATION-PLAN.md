# CALYX-BRAIN-002 — Reasoning Ledger and Memory Contracts

## Status

Implementation branch bootstrap for Issue #142.

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
