# CALYX-640 — Governed conversation source-to-project linking

Date: 2026-08-08
Depends on: CALYX-636 persistent conversations, CALYX-639 source document identity continuity, and the existing Research Workspace document-link service.
Status: implemented; exact-head validation pending. No merge, deployment, scientific publication, evidence-authority upgrade, or Knowledge Graph mutation authorized.

## Goal

Allow a researcher to explicitly save a source that Calyx actually used in a persisted conversation into that conversation's Research Workspace project without trusting a browser-supplied document identity or inferring provenance from title, DOI, lexical similarity, or model knowledge.

## Delivered

- authenticated owner-scoped `POST /brain/mission-control/chat/conversations/{conversation_id}/sources/{result_id}/project-link`;
- source lookup is restricted to compact source references already persisted in the requested conversation;
- the target project is taken from the persisted conversation rather than from the request body;
- document and revision identity come only from the persisted CALYX-639 citation;
- requests fail closed when the conversation has no project, the source is not in that conversation, or the source lacks an exact `document_id`;
- normal Research Workspace canonical document validation remains mandatory;
- normal Research Workspace document-link idempotency is reused, so repeating the same save does not create duplicate project-document rows;
- the caller may choose only the existing governed document relationship vocabulary: `SOURCE`, `BACKGROUND`, `METHOD`, or `CONTRADICTS`;
- response states explicitly that conversation history is not evidence and that scientific publication and Knowledge Graph mutation remain unauthorized;
- router is registered through the existing Mission Control registration path.

## Provenance and trust boundary

The request body contains no document ID, revision ID, project ID, title, DOI, or other source locator. The endpoint resolves all authoritative identity from the owner-scoped persisted conversation. This prevents a UI control from silently turning arbitrary user-supplied identifiers into project provenance.

The source reference itself remains a pointer to governed Continuum material. Saving that pointer to a Research Workspace project does not convert the Calyx answer or conversation transcript into scientific evidence.

## Failure behavior

The action fails closed for:

- missing or cross-owner conversation;
- conversation with no associated project;
- result ID not present among persisted conversation source refs;
- source ref without exact CALYX-639 `citation.document_id`;
- canonical Research Workspace document validation failure;
- archived or inaccessible project.

No fuzzy fallback is permitted.

## Validation plan

Dedicated CALYX-640 CI validates compilation; successful and repeat/idempotent source linking; owner isolation; unknown-source and missing-document failure paths; CALYX-639 source identity regressions; CALYX-638 report regressions; CALYX-636 persistence regressions; permanent source-bound and non-authority assertions; Ruff formatting/lint; and diff hygiene.

## Next priority after validation

Expose the action in the Research Station persistent Ask Calyx interface. The frontend should show `Save source to project` only for response evidence carrying exact `citation.document_id`, disable or mark already-linked documents based on the project's current document links, call only this conversation-bound endpoint, refresh project document links after success, and never automatically change active document retrieval scope.
