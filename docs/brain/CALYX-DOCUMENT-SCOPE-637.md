# CALYX-637 — Governed document-scoped conversation retrieval

Date: 2026-08-08
Depends on: CALYX-636 persistent conversation sessions.
Status: implemented, exact-head validation passed, and PR #651 is review-ready. No merge, deployment, publication, or Knowledge Graph mutation authorized.

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

## Validation evidence

Implementation head `2adb0614b9708516ef4813c72a4a91d3a179db85` passed all four triggered lanes:

- CALYX Document Scope 637;
- CALYX Continuum Conversation 634;
- CALYX Conversation Graph 635;
- CALYX Workflow Governance Audit.

The dedicated document-scope lane compiled the new surface, passed 18 focused + stacked Evidence Retrieval/conversation tests, passed permanent non-authority assertions, and passed Ruff/diff hygiene. Its first run had already passed all behavior tests and failed only four `RUF012` fixture annotations; those were corrected with `ClassVar` without changing runtime behavior.

PR #651 was then promoted from draft to review-ready and remains unmerged/non-production.

## Research Station handoff

RS-10 is implemented on branch `feature/research-calyx-document-scope-10` and opened as frontend PR #12, stacked on validated RS-9. It adds:

- project-linked document discovery;
- explicit all-evidence versus exact-document selection;
- persistent `active_document_id` create/ask routing;
- reopened-thread restoration of valid stored document scope;
- revision-to-document mapping;
- visible stale-scope handling instead of silent substitution;
- fail-closed messaging when a scoped document returns no eligible evidence;
- pure deterministic scope helpers with focused tests.

RS-10 remains draft and unmerged until its full Research Station exact-head formatting/lint/test/build gate passes.

This Brain update moves the CALYX-637 branch head beyond the validated implementation commit, so the same backend gates must revalidate this documentation-only exact head before it is treated as final.

Conversation history and routing context remain context, not evidence.
