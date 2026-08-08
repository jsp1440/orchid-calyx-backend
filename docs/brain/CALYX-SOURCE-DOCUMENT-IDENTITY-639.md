# CALYX-639 — Source document identity continuity

Date: 2026-08-08
Depends on: CALYX-637 governed document scope and CALYX-638 persistent conversation reports.
Status: implemented; exact-head validation pending. No merge, deployment, scientific publication, or Knowledge Graph mutation authorized.

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

## Validation plan

Dedicated CALYX-639 CI validates compilation; exact source-document propagation through retrieval, persistent source references, and Markdown reports; CALYX-637 document-scope regressions; CALYX-638 report regressions; non-authority source assertions; Ruff formatting/lint; and diff hygiene.

## Next priority after validation

Expose an explicit Research Station `Save source to project` action only for Calyx evidence records that contain the governed `citation.document_id`. The action should create a normal Research Workspace document link with the exact document and revision identity, remain idempotent, and never convert the Calyx answer itself into scientific evidence.
