# CALYX-637 — Governed document-scoped conversation retrieval

Date: 2026-08-08
Depends on: CALYX-636 persistent conversation sessions.
Status: implemented; exact-head validation pending. No merge, deployment, publication, or Knowledge Graph mutation authorized.

## Goal

Make `active_document_id` operational rather than passive session metadata. When a researcher explicitly supplies or inherits an active document in an Ask Calyx conversation, Evidence Retrieval must be constrained to indexed evidence belonging to that document identity.

## Delivered

- `ContinuumConversationService` converts non-empty `active_document_id` into `RetrievalQuery.filters={"document_id": ...}`;
- Evidence Retrieval applies an exact document-identity gate before ranking;
- accepted document identities are exact matches against indexed `revision_id`, `parent_id`, `metadata.document_id`, or `metadata.source_document_id`;
- evidence from other documents is excluded and counted under `DOCUMENT_SCOPE`;
- the conversation tool trace reports `document_scope` and `document_scope_applied`;
- no active document preserves existing global Continuum retrieval behavior;
- conversation schema advances to `calyx-continuum-conversation/v3`;
- focused tests cover exact source-document, revision, and parent matching plus conversation query propagation.

## Why this matters

CALYX-636 could persist `active_document_id`, but CALYX-634/635 retrieval did not consume it. A reopened research thread could therefore appear document-scoped while still searching the global eligible evidence corpus. CALYX-637 removes that mismatch.

The filter is intentionally exact and fail-closed. Calyx does not fuzzy-match an active document identifier and does not silently broaden to global retrieval when the document scope yields no evidence. A no-result scoped query remains an explicit no-evidence response.

## Epistemic and authority boundary

Document scope changes candidate eligibility only. It does not change evidence authority, ranking provenance, display policy, review state, verification state, or citation authority.

Permanent constraints remain:

- model-memory fallback is disabled;
- scientific interpretation is not generated;
- scientific publication is not authorized;
- Knowledge Graph mutation is not authorized;
- read-only graph context remains separately governed by explicit taxon context.

## Validation

Dedicated `CALYX Document Scope 637` CI validates:

- compilation;
- exact document exclusion behavior;
- revision/parent identity compatibility;
- conversation propagation into `RetrievalQuery.filters`;
- CALYX-634 conversation regressions;
- BUILD-085B Evidence Retrieval regressions;
- source-level non-authority assertions;
- Ruff and diff hygiene.

Existing CALYX-634, CALYX-636, legacy Mission Control chat, and workflow-governance lanes may also trigger from the stacked changes and remain authoritative regressions.

## Next priority after validation

Expose project-linked document selection in Research Station persistent Ask Calyx, restore the stored document scope when reopening a thread, and make evidence-only/global retrieval an explicit selectable state. Conversation history remains context, not evidence.
