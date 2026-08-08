# CALYX-636 — Persistent research conversation sessions

Date: 2026-08-08
Depends on: CALYX-635 graph-grounded Ask Calyx, Research Station persistent workspace foundation.
Status: implementation behavior validated; final exact-head rerun pending after formatter/legacy-CI corrections. No merge, deployment, publication, external communication, or Knowledge Graph mutation authorized.

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

The first complete CALYX-636 behavioral run passed all 13 persistence + stacked conversation/graph tests and permanent conversation-memory non-authority assertions. The global workflow-governance audit also passed.

The remaining failures identified during validation were CI/hygiene defects rather than behavioral defects:

1. Ruff requested import normalization and `dict.get` simplification in the expanded chat router; those were corrected without changing behavior.
2. The legacy `CALYX-MISSION-CONTROL-003B Chat API` workflow installed only FastAPI/httpx/pytest/Ruff, so the now database-backed router could not import SQLAlchemy. The workflow was corrected to install the repository production requirements.
3. The next legacy run reached Ruff successfully and exposed only formatter normalization in the chat router. Commit `d475e3dda89447c392090fe5585c6320fc9f5457` applies exactly that formatter output.
4. The formatter commit was authored through the repository Copilot integration, which caused GitHub to mark the immediate pull-request workflow runs `action_required` before creating jobs. This was not a code failure. This Brain update intentionally creates a fresh exact head through the normal repository connector so all four gates can execute again.

Before that action-required head, the latest runnable head had already passed:

- CALYX Conversation Sessions 636;
- CALYX Continuum Conversation 634 compatibility;
- CALYX Workflow Governance Audit.

The legacy 003B lane's only remaining runnable failure was Ruff formatting, now corrected.

## Exact-head gate required before promotion

CALYX-636 remains draft until a fresh head passes all four lanes:

- CALYX Conversation Sessions 636;
- CALYX Continuum Conversation 634;
- CALYX-MISSION-CONTROL-003B Chat API;
- CALYX Workflow Governance Audit.

No gate is to be weakened to obtain promotion.

## Next priority after validation

Expose persistent session creation/list/history in Research Station so the project-scoped Ask Calyx page can reopen a prior research thread and continue it through the persistent endpoint.

Persistent dialogue is research context, not scientific evidence.
