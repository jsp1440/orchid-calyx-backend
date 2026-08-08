# CALYX-638 — Persistent conversation report export

Date: 2026-08-08
Depends on: CALYX-636 persistent conversation sessions and CALYX-637 document-scoped retrieval.
Status: implemented; exact-head validation pending. No merge, deployment, scientific publication, or Knowledge Graph mutation authorized.

## Goal

Allow an owner to download a persistent Ask Calyx research thread as a readable Markdown artifact while preserving its epistemic and provenance boundaries.

## Delivered

- pure Markdown report builder for a stored conversation detail;
- authenticated owner-scoped `GET /brain/mission-control/chat/conversations/{conversation_id}/report` endpoint;
- attachment filename `calyx-conversation-{conversation_id}.md`;
- conversation metadata and active project/taxon/document routing context;
- chronological researcher/Calyx transcript;
- per-answer recorded epistemic status;
- deduplicated compact source-reference ledger using persisted result/revision/identifier/locator metadata;
- explicit governance and interpretation-boundary sections;
- chat status capability flag for persistent conversation reports.

## Preservation model

The report does not rerun Evidence Retrieval, regenerate an answer, or create a new scientific interpretation. It exports the already persisted private research context and compact source references associated with the thread.

Conversation text remains `CONVERSATION_CONTEXT`, not evidence. Source references remain the authority for any scientific claim. The export itself does not alter review state, publication state, evidence state, or Knowledge Graph state.

## Security and ownership

The endpoint reuses the CALYX-636 owner-scoped conversation lookup. A conversation belonging to another owner resolves as not found. There is no privileged cross-owner export path.

## Permanent non-authority declarations

Every report states:

- conversation context is not scientific evidence;
- evidence authority is false;
- scientific publication is not authorized;
- Knowledge Graph mutation is not authorized;
- model-memory evidence authority is false;
- the report is not a peer-reviewed scientific conclusion.

## Validation plan

Dedicated CALYX-638 CI validates:

- compilation;
- report content and governance language;
- source-reference deduplication;
- authenticated Markdown attachment response;
- cross-owner isolation;
- CALYX-636 persistence regressions;
- CALYX-637 document-scope regressions;
- permanent non-authority source assertions;
- Ruff formatting/lint and diff hygiene.

## Next priority after validation

Expose a `Download report` control on the Research Station persistent Ask Calyx thread, using the same authenticated owner session and preserving the server-provided attachment filename.
