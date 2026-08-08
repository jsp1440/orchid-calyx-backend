# CALYX-638 — Persistent conversation report export

Date: 2026-08-08
Depends on: CALYX-636 persistent conversation sessions and CALYX-637 document-scoped retrieval.
Status: implemented and exact-head validated; PR #654 is review-ready and unmerged. No deployment, scientific publication, or Knowledge Graph mutation authorized.

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

## Validation

The implementation head `b23f03fa9ab30c97316061d9835bec14e9927a02` passed all five triggered gates after canonical formatting fixes:

- CALYX Conversation Report 638;
- CALYX Conversation Sessions 636;
- CALYX Continuum Conversation 634;
- CALYX-MISSION-CONTROL-003B Chat API;
- CALYX Workflow Governance Audit.

The dedicated report suite covered compilation, report content/governance language, source-reference deduplication, authenticated Markdown attachment response, cross-owner isolation, CALYX-636 persistence regressions, CALYX-637 document-scope regressions, permanent non-authority assertions, Ruff formatting/lint, and diff hygiene.

The first CALYX-638 run had already passed all 11 behavioral/regression tests and governance assertions; its only failure was canonical formatting in the new report/test files. Those exact formatting differences were applied before the fully green head above.

## Research Station handoff

RS-11 implements the corresponding `Download report` control using the same authenticated owner session and the server-generated CALYX-638 artifact. Its implementation head `562bfa4f373aa48d608bd60dfb1d3a391ca11b36` passed the complete Research Station formatting, lint, Vitest, and production-build gate and PR #13 was promoted to review-ready. RS-11 additionally sanitizes both server-provided and deterministic fallback filenames before assigning the browser download filename.

## Next priority

Continue conversational-workbench integration without changing evidence authority: improve persistent research-thread navigation and source reuse only through explicit, provenance-preserving controls. Merge/deployment remains a governance boundary.
