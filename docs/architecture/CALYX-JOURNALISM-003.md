# CALYX-JOURNALISM-003 — Durable persistence and agent orchestration

## Purpose

Replace the same-process stores introduced by the journalism MVP with owner-scoped durable records while preserving the evidence-first article contract.

## Durable artifacts

- `calyx_journalism_evidence_packets`
- `calyx_journalism_articles`

Each record contains an immutable identifier, owner and actor provenance, generation mode, canonical JSON payload, request metadata, and creation timestamp.

## API additions

Existing creation and export routes retain their contracts. New authenticated retrieval routes are:

- `GET /brain/journalism/evidence-packets/{packet_id}`
- `GET /brain/journalism/articles/{article_id}`

All lookups are owner-scoped. A record owned by another subject is returned as not found.

## Calyx-agent bridge

Natural-language requests containing article, report, journalism, newsletter, or similar terms cause the governed agent to inspect `journalism.readiness` and prepare an evidence-grounded journalism workflow. This does not call an external model and does not publish anything.

Direct scientific-publication requests continue to be blocked pending the canonical scientific approval gate.

## Operational boundary

The SQL migration is included but is not executed automatically. Deployment and production migration require explicit owner approval. The article generator remains deterministic and contract-based until a separately governed provider adapter is implemented.
