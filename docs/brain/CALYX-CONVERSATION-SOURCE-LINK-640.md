# CALYX-640 — Governed conversation source-to-project linking

Date: 2026-08-08
Depends on: CALYX-636 persistent conversations, CALYX-639 source document identity continuity, and the existing Research Workspace document-link service.
Status: implementation exact-head validated, review-ready, mergeable, and unmerged. No merge, deployment, scientific publication, evidence-authority upgrade, or Knowledge Graph mutation authorized.

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
- successful first-time linking retains the normal Research Workspace `DOCUMENT_LINKED` audit event;
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

## Validation and corrections

Dedicated CALYX-640 CI validates compilation; successful and repeat/idempotent source linking; owner isolation; unknown-source and missing-document failure paths; CALYX-639 source identity regressions; CALYX-638 report regressions; CALYX-636 persistence regressions; permanent source-bound and non-authority assertions; Ruff formatting/lint; and diff hygiene.

Corrective validation history:

1. Mission Control live-registration lint exposed noncanonical import wrapping after mounting the new router. The import was canonically formatted.
2. The source-link integration test then reached the real Research Workspace audit path and exposed that the SQLite fixture omitted `audit_events`. The fixture was corrected rather than weakening production behavior, and now asserts exactly one `DOCUMENT_LINKED` audit event for repeated/idempotent saves.
3. Mission Control live-registration then exposed that its legacy workflow installed only lightweight FastAPI test dependencies while the mounted source-link router legitimately depends on SQLAlchemy. The workflow now installs the repository's real application requirements before registration testing.
4. The dedicated behavioral gate subsequently passed 12 source-link/provenance/report/session tests plus permanent non-authority assertions. Ruff identified only canonical line wrapping in the new router and test fixture; those exact formatter changes were applied by GitHub Copilot.
5. The Copilot-authored formatting head was marked `action_required` by repository Actions policy before jobs could run. A user-authored Brain commit restored executable validation without altering runtime behavior.
6. Exact implementation head `8e3140289946b0612fdf7c1c6abfa0e55c1a52ae` passed all three required lanes: CALYX Conversation Source Link 640, CALYX-MISSION-CONTROL-003C Live Registration, and CALYX Workflow Governance Audit. The dedicated lane passed compilation, 12 integrated tests, permanent provenance/non-authority assertions, Ruff, formatting, and diff hygiene.
7. PR #679 was marked ready for review after the exact-head green result. It remains unmerged and non-production.

## Next priority

Expose the action in the Research Station persistent Ask Calyx interface. The frontend should show `Save source to project` only for response evidence carrying exact `citation.document_id`, disable or mark already-linked documents based on the project's current document links, call only this conversation-bound endpoint, refresh project document links after success, and never automatically change active document retrieval scope.
