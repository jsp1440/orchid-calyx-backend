# BUILD-034 — Constitutional Mission Orchestrator

## Objective

Give Calyx a constitutional autonomy layer so it can evaluate proposed work, assign delegated authority, record decision rationale, raise governance questions, and preserve rollback checkpoints before autonomous execution expands.

This build does **not** grant unsafe production write authority. It creates the guardrail system needed before Calyx begins continuous mission work.

## Implemented

### Constitutional Orchestrator

- `runtime/constitutional_orchestrator.py`

Provides:

- Autonomy levels 0–4
- Policy registry
- Mission registry
- Decision ledger
- Governance question queue
- Rollback checkpoint identifiers
- Action evaluation under constitutional guardrails

### Runtime API endpoints

The orchestrator is exposed through runtime endpoints:

- `GET /api/runtime/constitutional/status`
- `GET /api/runtime/constitutional/policies`
- `GET /api/runtime/constitutional/missions`
- `GET /api/runtime/constitutional/decision-ledger`
- `GET /api/runtime/constitutional/governance-questions`
- `POST /api/runtime/constitutional/evaluate`

### Runner API endpoints

BUILD-034 also adds a dedicated runner-oriented router:

- `runtime/constitutional_router.py`

Exposed endpoints:

- `GET /api/runner/constitutional/status`
- `GET /api/runner/constitutional/policies`
- `GET /api/runner/constitutional/missions`
- `GET /api/runner/constitutional/decision-ledger`
- `GET /api/runner/constitutional/governance-questions`
- `POST /api/runner/constitutional/evaluate`

### Main application wiring

- `app/main.py`

Updates:

- Runner mode reports `build_034_constitutional_orchestrator`.
- Runner summary includes `Constitutional Orchestrator`.
- `run-once` enqueues `optimize_constitutional_orchestrator`.
- `execute-next` can run `optimize_constitutional_orchestrator`.
- The constitutional router is included in FastAPI startup.

### Governance schema foundation

- `migrations/BUILD-034-constitutional-orchestrator.sql`

Creates:

- `oc_governance.missions`
- `oc_governance.policies`
- `oc_governance.decision_ledger`
- `oc_governance.governance_questions`
- `oc_governance.checkpoints`

## Autonomy levels

| Level | Name | Meaning |
|---|---|---|
| 0 | Observe | Read, inspect, summarize, and recommend only. |
| 1 | Safe operations | Safe reversible operations such as reports, monitoring, and cache-style work. |
| 2 | Propose | Prepare plans, patches, docs, branches, and pull requests for review. |
| 3 | Trusted execution | Limited predefined reversible execution. |
| 4 | Owner approval required | High-risk actions stop for owner review. |

## Guardrail rule

> Calyx may optimize execution, but it may never rewrite purpose.

Purpose remains governed by:

- BUILD-031 Founding Charter
- Orchid Continuum Constitution
- Explicit owner directives
- Future constitutional amendments and precedents

## High-risk actions

The orchestrator treats the following as requiring owner review:

- deployments
- schema changes
- authentication/security changes
- secrets or credentials
- deletion/destructive operations
- constitutional changes
- actions without rollback/provenance when policy requires them

## Mission registry

Initial missions:

- Engineering
- Science
- Education
- Conservation
- Funding
- Community
- Institutional Memory

These are the durable mission lanes that later continuous Calyx loops will use to coordinate literature extraction, Vision AI, Matrix systems, glossary, Orchid University, pollinators, mycorrhizae, mapping, federation connectors, grant work, and frontend repairs.

## Deployment

This is a backend build. After merge, redeploy the Calyx backend.

## Next build

BUILD-035 should connect Mission Control to these constitutional endpoints so the owner can see:

- current mission registry
- policy registry
- decision ledger
- governance questions
- a live action evaluation form
