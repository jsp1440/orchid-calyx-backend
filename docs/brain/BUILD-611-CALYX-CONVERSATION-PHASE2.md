# BUILD-611 — Calyx Conversational Analysis Phase 2

Date: 2026-08-08
Status: implemented on branch; validation required before merge

## Purpose

Make Calyx directly usable as the Orchid Continuum's conversational and quantitative analysis surface rather than merely documenting a future conversational architecture.

## Implemented

1. Corrected the BUILD-610 embedding-provider import so the Calyx router imports the actual `app.semantic_index.provider.DeterministicLocalProvider` implementation.
2. Added persistent conversation storage backed by PostgreSQL when `DATABASE_URL` is configured, with an explicit memory fallback for isolated tests/local development.
3. Added conversation transcript retrieval and recent-conversation endpoints.
4. Added direct read-only Knowledge Graph context retrieval for node ID, taxon ID, or genus.
5. Added direct read-only Brain graph queries with node type, canonical key, text, and edge filters.
6. Expanded deterministic mathematical analysis with covariance, confidence intervals, moving averages, quartiles, standard error, and regression residual diagnostics.
7. Added Julius-style tabular analysis primitives: dataset description and numeric correlation matrices from column-oriented JSON data.
8. Expanded report generation to include dataset results, Knowledge Graph context, Brain results, evidence ledger, retrieval diagnostics, and governance notice.
9. Added migration `610_calyx_conversations.sql` for persistent conversation and message tables.
10. Added a dedicated GitHub Actions workflow that compiles, tests, lints, and verifies Calyx route registration whenever the conversation surface changes.

## Governance boundary

BUILD-611 is intentionally read/analyze-only. It does not automatically publish scientific claims, mutate canonical Knowledge Graph state, alter governance, or promote conversational outputs into established knowledge. Those transitions remain governed actions.

## Operational objective

The immediate user-facing objective is to support a persistent Calyx workspace in which an authenticated operator can ask Continuum questions, run quantitative analyses, inspect Brain and Knowledge Graph context, and download evidence-bearing reports.

## Next priorities after validation

- file/table upload ingestion for CSV/XLSX into the analysis surface;
- chart-ready result specifications and frontend visualization;
- richer tool planning so natural-language requests can automatically select evidence, graph, Brain, and quantitative tools;
- model-backed synthesis constrained by retrieved evidence and explicit uncertainty;
- Mission Control/Research Station frontend chat workspace;
- voice input/output on top of the same governed conversation API.
