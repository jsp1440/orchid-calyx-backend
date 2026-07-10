# BUILD-052 Calyx Executive Intelligence Engine

## Architecture

BUILD-052 adds a deterministic read-only executive reasoning layer under `runtime/executive/`.

- `telemetry.py` aggregates Mission Control metrics, completeness rows, harvester state, runtime jobs, governance, and recommendation sources.
- `dependencies.py` defines the executive dependency graph and reverse dependencies.
- `scorer.py` computes weighted priority scores.
- `recommendations.py` emits evidence-backed recommendations only.
- `reasoning.py` attaches deterministic explanations to priorities.
- `summarizer.py` generates executive summaries and briefings.
- `engine.py` assembles the single executive state and performs in-memory change detection.
- `executive_state.py` defines the normalized subsystem schema.

No LLM is required. No endpoint writes to production data.

## Executive State Schema

Each subsystem contains:

- `id`
- `name`
- `category`
- `status`
- `health`
- `completion`
- `dependencies`
- `blockers`
- `owner_required`
- `confidence`
- `last_updated`
- `source`
- `summary`
- `metrics`

The aggregate state contains:

- `build`
- `generated_at`
- `subsystems`
- `dependencies.graph`
- `dependencies.reverse`
- `priorities`
- `recommendations`
- `changes`
- `summary`
- `briefing`

## Reasoning Pipeline

1. Collect available backend telemetry from Mission Control, harvesters, runtime, and governance.
2. Normalize every executive subsystem into the shared schema.
3. Construct dependency and reverse-dependency maps.
4. Score priorities with weighted factors:
   - Scientific impact
   - Conservation impact
   - Research impact
   - Owner value
   - Dependency blocking
   - Risk
   - Build readiness
   - Evidence confidence
   - Freshness
5. Attach deterministic reasoning to the ordered priority list.
6. Generate evidence-backed recommendations.
7. Compare the current state against the previous in-memory state to identify changes.
8. Produce executive summary and briefing payloads.

## API

All endpoints are read-only:

- `GET /api/executive/state`
- `GET /api/executive/summary`
- `GET /api/executive/priorities`
- `GET /api/executive/recommendations`
- `GET /api/executive/changes`
- `GET /api/executive/dependencies`
- `GET /api/executive/briefing`

## Frontend Consumption

Mission Control should consume `/api/executive/state` as its first source of truth for:

- Executive Summary
- Priority Queue
- Recommendation Cards
- Completeness Matrix
- Attention Summary
- Daily Brief
- Now Working
- Decision Queue
- Global Health
- Subsystem Status

Legacy `/api/mission-control/*` probes remain fallback/compatibility inputs.

## Future Expansion

- Persist executive snapshots for durable change history.
- Add source-specific freshness timestamps for each subsystem.
- Add backend-owned GitHub/Render deployment telemetry.
- Add deeper Brain/knowledge-graph coverage once the production schema is finalized.
- Add export formats after server-side document generation libraries are approved.

