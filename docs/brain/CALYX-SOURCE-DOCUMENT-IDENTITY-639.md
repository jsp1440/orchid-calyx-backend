# CALYX-639 — Source document identity continuity

Date: 2026-08-08
Depends on: CALYX-637 governed document scope and CALYX-638 persistent conversation reports.
Status: implemented and exact-head validated; PR #657 is review-ready and unmerged. No deployment, scientific publication, or Knowledge Graph mutation authorized.

## Goal

Preserve the exact indexed source-document identity across Evidence Retrieval, persistent Calyx source references, and conversation reports so a researcher can navigate or explicitly reuse the same governed source without inferring identity from a title, DOI, or revision alone.

## Delivered

- Evidence Retrieval citations now include `document_id`, resolved from indexed `metadata.source_document_id` and then `metadata.document_id`;
- existing exact document-scope matching remains unchanged and continues to accept revision, parent, document, or source-document identity;
- CALYX conversation evidence records preserve the retrieval citation unchanged;
- CALYX-636 persistent compact `source_refs` now retain both `document_id` and `revision_id`;
- CALYX-638 Markdown source ledgers display the persisted document ID alongside revision, identifier, locator, and title;
- focused tests cover retrieval identity, persistent source-ref identity, report identity, and permanent non-authority language.

## Provenance rule

`document_id` is copied only from indexed metadata already attached to the retrieved record. Calyx does not derive a document ID from document title, DOI, lexical similarity, model memory, or another fuzzy mapping. When no indexed document identity exists, the citation returns no document ID and downstream project-link actions must remain unavailable rather than guess.

## Authority boundary

Source identity improves provenance continuity only. It does not:

- make conversation history evidence;
- change source review or verification state;
- authorize a scientific conclusion;
- authorize publication;
- create or mutate Knowledge Graph state.

## Validation

The initial CALYX-639 behavioral head passed all focused source-identity/document-scope/report tests and provenance/non-authority assertions; its only failure was canonical formatting in the changed conversation-memory file. After that correction, CALYX-639 itself was green, but the stacked CALYX-638 lane exposed a separate unformatted source-anchor assertion on the parent branch.

The parent CALYX-638 branch was corrected and independently revalidated. CALYX-639 was then rebuilt on that clean parent rather than relying on a synthetic merge. Canonical rebased implementation head `d98297a338ccb5c35ac8e7b10363deb78bae62fa` passed all seven triggered lanes:

- CALYX Source Document Identity 639;
- CALYX Conversation Report 638;
- CALYX Document Scope 637;
- CALYX Conversation Sessions 636;
- CALYX Continuum Conversation 634;
- CALYX-MISSION-CONTROL-003B Chat API;
- CALYX Workflow Governance Audit.

This rebased head preserves CALYX-638 source-anchor report navigation and adds source-document identity continuity without regression.

## Next priority

Expose an explicit Research Station `Save source to project` action only for Calyx evidence records that contain the governed `citation.document_id`. The action should create a normal Research Workspace document link with the exact document and revision identity, avoid duplicate links, and never convert the Calyx answer itself into scientific evidence.
