# CALYX-636 — Persistent research conversation sessions

Date: 2026-08-08
Depends on: CALYX-635 graph-grounded Ask Calyx, Research Station persistent workspace foundation.
Status: implementation validated and PR #646 promoted to review on exact head `c9bde5c476b65baa096e848349ec16e3be630bb1`. No merge, deployment, publication, external communication, or Knowledge Graph mutation authorized.

## Goal

Give Calyx durable, owner-scoped research conversation continuity without converting dialogue into scientific evidence or canonical knowledge.

CALYX-636 adds persistent conversation sessions and append-only messages inside the existing `research_station` data boundary.

## Persistence model

`research_station.conversation_sessions` stores:

- owner subject;
- optional project binding;
- title;
- current taxon/document routing context;
- created/updated/archive timestamps;
- optimistic version counter.

`research_station.conversation_messages` stores:

- owner-scoped conversation ID;
- role (`OPERATOR` or `CALYX`);
- message content;
- Calyx epistemic status when applicable;
- routing context snapshot;
- compact evidence source references only;
- tool trace;
- immutable governance fields.

Messages are append-only at the database layer: a trigger rejects UPDATE and DELETE.

## Epistemic boundary

Every persistent conversation/session response declares:

- `data_status=CONVERSATION_CONTEXT`;
- `evidence_authority=false`;
- `scientific_publication_authorized=false`;
- `knowledge_graph_mutation_authorized=false`.

Conversation history is not inserted into Evidence Retrieval queries and is not promoted into Knowledge Graph facts. The current question remains the retrieval query. Stored session context may supply project/taxon/document routing identifiers when the current request omits them; an explicit request value, including `null`, overrides the stored context for that turn.

## Evidence storage minimization

Calyx answers may display authorized excerpts in the live response, but persistent message `source_refs` store only compact provenance references:

- retrieval result ID;
- object type/title;
- revision ID;
- identifier;
- locator;
- document title.

The authorized excerpt itself is not duplicated into `source_refs_json`.

## API

Existing stateless `POST /brain/mission-control/chat/ask` remains compatible and explicitly returns `persistent=false`.

New authenticated endpoints:

- `POST /brain/mission-control/chat/conversations` — create owner-scoped session;
- `GET /brain/mission-control/chat/conversations` — list owner sessions, optionally by project;
- `GET /brain/mission-control/chat/conversations/{conversation_id}` — retrieve session and append-only message history;
- `POST /brain/mission-control/chat/conversations/{conversation_id}/ask` — Ask the Continuum using stored routing context plus explicit per-turn overrides, then persist the operator/Calyx exchange.

Conversation access does not use privileged cross-owner bypass. A conversation ID owned by another subject resolves as not found.

## Validation evidence

Exact head `c9bde5c476b65baa096e848349ec16e3be630bb1` passed all required lanes:

- CALYX Conversation Sessions 636;
- CALYX Continuum Conversation 634 compatibility;
- CALYX-MISSION-CONTROL-003B Chat API;
- CALYX Workflow Governance Audit.

The CALYX-636 lane includes the persistence + stacked conversation/graph suite and permanent conversation-memory non-authority assertions. An earlier complete behavioral run recorded 13 passing persistence/conversation/graph tests before the final CI hygiene corrections.

Validation exposed and corrected CI/hygiene defects without broadening authority:

1. Ruff import normalization and `dict.get` simplification in the expanded chat router.
2. The legacy 003B workflow previously installed only FastAPI/httpx/pytest/Ruff and could not import the production SQLAlchemy-backed router. It now installs `requirements.txt` plus test tooling.
3. Ruff formatter normalization was applied to the chat router.
4. A Copilot-authored formatter commit temporarily produced GitHub `action_required` workflow states with no jobs. A normal connector-authored Brain commit created fresh runnable checks; the resulting exact head passed all four gates.

PR #646 was then marked ready for review. It remains unmerged and non-production.

## Research Station integration

RS-9 was started immediately after backend validation. Its purpose is to expose CALYX-636 session creation, listing, reopening, history, and persistent follow-up inside the project-scoped Ask Calyx workspace while keeping dialogue visibly labeled as non-evidence research context.

Persistent dialogue is research context, not scientific evidence.
