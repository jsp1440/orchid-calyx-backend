# CALYX-636 — Persistent research conversation sessions

Date: 2026-08-08
Depends on: CALYX-635 graph-grounded Ask Calyx, Research Station persistent workspace foundation.
Status: implementation pending exact-head validation; no merge, deployment, publication, external communication, or Knowledge Graph mutation authorized.

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

Existing stateless `POST /brain/mission-control/chat/ask` remains compatible and now explicitly returns `persistent=false`.

New authenticated endpoints:

- `POST /brain/mission-control/chat/conversations` — create owner-scoped session;
- `GET /brain/mission-control/chat/conversations` — list owner sessions, optionally by project;
- `GET /brain/mission-control/chat/conversations/{conversation_id}` — retrieve session and append-only message history;
- `POST /brain/mission-control/chat/conversations/{conversation_id}/ask` — Ask the Continuum using stored routing context plus explicit per-turn overrides, then persist the operator/Calyx exchange.

Conversation access does not use privileged cross-owner bypass. A conversation ID owned by another subject resolves as not found.

## Validation plan

Dedicated CALYX-636 CI will validate:

- SQLite-backed owner-scoped create/ask/read round trip;
- project context inheritance;
- taxon context inheritance and explicit clearing;
- two-message append per successful exchange;
- compact source references without duplicated excerpts;
- cross-owner isolation;
- migration append-only and non-authority constraints;
- CALYX-634 and CALYX-635 regression compatibility;
- compilation, Ruff, and diff hygiene;
- source-level assertions that conversation memory does not import publication or writable graph systems.

## Next priority after validation

Expose persistent session creation/list/history in Research Station so the project-scoped Ask Calyx page can reopen a prior research thread and continue it through the persistent endpoint.

Persistent dialogue is research context, not scientific evidence.
