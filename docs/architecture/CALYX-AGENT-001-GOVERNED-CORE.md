# CALYX-AGENT-001 — Governed Conversational Core

## Purpose

This build begins the transition from a deterministic Brain interface to a governed internal AI operator for the Orchid Continuum.

The initial slice is intentionally bounded. It accepts natural-language requests, classifies their intent and risk, invokes registered read-only internal tools, produces dependency-aware steps, and converts consequential requests into explicit approval requirements. It does not yet provide unrestricted model-driven autonomy.

## API

- `GET /brain/agent/capabilities`
- `POST /brain/agent/requests`

Both routes inherit the existing Brain owner-session or API-key authentication boundary.

## Implemented capabilities

- natural-language request intake;
- deterministic intent and risk classification;
- reviewable structured plans;
- three registered read-only tools:
  - Brain readiness;
  - Mission Control readiness;
  - Continuum build inventory;
- prepare-only build and monitoring steps;
- owner-approval blocking for mutations;
- separate scientific-approval blocking for canonical publication;
- provider configuration status;
- explicit source, warning, uncertainty, and tool-result reporting;
- no private chain-of-thought request or persistence.

## Provider boundary

`CALYX_AGENT_PROVIDER` and `CALYX_AGENT_MODEL` declare provider configuration. This slice does not call an external provider. When either value is absent, Calyx reports `not_configured` and uses deterministic planning only.

A later slice must add a credential-safe provider adapter with bounded context assembly, redaction, timeouts, cost budgets, and auditable provider calls.

## Governance model

### Automatic read-only

Inspection, capability discovery, audit planning, diagnostics, and evidence collection.

### Prepare-only

Build specifications, monitoring specifications, dependency maps, test plans, and draft work plans.

### Owner approval

Repository mutations, issue/branch/commit/PR creation, merges, deployments, migrations, imports, schedule changes, or any production-state mutation.

### Scientific approval

Canonical scientific approval and publication remain governed by the Reasoning Ledger, human review, and BUILD-088 publication gate.

Request text cannot grant its own approval.

## Relationship to existing architecture

This package reuses the authenticated Brain router and does not create a second Knowledge Graph, reasoning store, connector registry, publication pathway, or autonomous runtime.

## Known limitations

- no durable agent session or tool-call persistence yet;
- no external model invocation yet;
- build inventory is code-declared rather than repository-adapter driven;
- no approved mutation executor;
- no long-running job queue or cancellation yet;
- no Echo-derived curated memory import yet;
- no frontend conversational chat wiring yet.

## Next dependency-safe slices

1. Durable PostgreSQL session, message, plan, tool-call, result, and approval records.
2. Credential-safe provider adapter and retrieval-context assembler.
3. Live read-only adapters for Brain, Reasoning Ledger, Mission Control, harvesters, archive, and repository inventory.
4. Approval workflow for prepare-only GitHub mutations that can create issues, branches, patches, tests, and Draft PRs but cannot merge.
5. Long-running audit/build jobs, cancellation, budgets, and Mission Control telemetry.
6. Curated Echo institutional-memory ingestion with provenance, classification, supersession, and access controls.

## Deployment status

No production deployment, migration, provider credential, autonomous mutation, scientific publication, or GitHub mutation is performed by this build.
