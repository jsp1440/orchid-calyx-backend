# BUILD-074 — Unified Calyx Executive Intelligence

This build consolidates the recommendation engine, provider-neutral AI routing, AI budget management, and external-service recommendation foundation.

## Implemented foundation

- Deterministic, evidence-linked recommendations for approved intake sources.
- Recommendation queue and approve/reject decision contract.
- Provider capability, health, priority, cost-rank, managed/BYOAI metadata.
- Workspace/project budget policies with soft and hard limits.
- Cost-aware provider routing and fallback ordering.
- AI usage ledger with workflow and recommendation provenance.
- Additive owner/API-key protected API under `/api/executive-intelligence`.
- No canonical taxonomy or knowledge-graph mutation.

## Deployment

Apply `migrations/074_unified_executive_intelligence.sql` after BUILD-070 and BUILD-072 migrations. Provider credentials must remain in the platform secret store or environment and must never be written to these tables.

## Deferred within the combined build

- Converting approved recommendations directly into `oc_workflow.actions` in one transaction.
- Provider adapters that execute real model calls.
- Mission Control frontend queue, daily briefing, and budget dashboard.
- Usage reconciliation from provider invoices.

All deferred execution remains approval-gated.
