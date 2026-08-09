# CALYX Conversation Current-Main Reconstruction 714

Status: IMPLEMENTED ON CURRENT MAIN / EXECUTABLE CI BLOCKED BY #481

## Purpose

Reconstruct the useful Ask Calyx conversation stack directly on the current `main` lineage instead of attempting to carry forward stale stacked ancestry. The first reconstruction PR #714 later fell behind `main`; this v2 branch was rebuilt directly from the current `main` parent and layers only the conversation-specific delta.

## Delivered

- Retrieval-grounded `POST /brain/mission-control/chat/ask` with no general-model evidence fallback.
- Optional active taxon context through a bounded, read-only Knowledge Graph traversal adapter.
- Owner-scoped persistent research conversation sessions and append-only messages.
- Exact active-document scoping through Evidence Retrieval.
- Canonical source-document identity preservation in citations and persisted source references.
- Markdown conversation reports with a deduplicated source ledger and explicit non-evidence boundary.
- Owner-scoped `Save source to project` action that resolves project/document/revision identity from persisted conversation provenance rather than caller-supplied document identity.
- Current Mission Control registration for both the chat and source-link routers.
- Forward-only migration `140_calyx_conversation_sessions.sql`; it is included but not applied to production.
- Focused current-main regression test and dedicated read-only CI workflow.

## Current-main reconstruction discipline

The v2 reconstruction starts from current `main` rather than rebasing the old conversation branch mechanically. Added conversation files were reconstructed from the reviewed #714 implementation. Shared files were reapplied against the current `main` versions so unrelated intervening changes are not overwritten.

The resulting delta intentionally remains limited to conversation memory, source linking, exact document scoping, read-only graph context, Mission Control registration, migration, tests, CI, and Brain documentation.

## Corrective document identity boundary

Active-document matching uses only canonical document namespaces: `metadata.document_id` and `metadata.source_document_id`. Revision IDs and parent IDs are independent namespaces and are deliberately excluded from the document-scope gate.

The regression suite includes a positive canonical document-ID match and negative revision/parent collision checks. CI statically rejects reintroduction of revision/parent matching into the scope gate.

## Evidence and publication governance

Conversation history is `CONVERSATION_CONTEXT`, not scientific evidence. Model-memory evidence authority is disabled. Knowledge Graph access is read-only. Scientific publication and Knowledge Graph mutation remain unauthorized. Saving a source to a Research Workspace project preserves provenance but does not promote, publish, or canonize the source.

The database migration enforces append-only conversation messages and permanently constrains `evidence_authority`, `scientific_publication_authorized`, and `knowledge_graph_mutation_authorized` to false for persisted messages.

No production migration, deployment, scientific publication, taxonomy activation, credential change, or production Knowledge Graph mutation is authorized by this build.

## Validation

Dedicated workflow: `CALYX Conversation Current Main 714`.

The executable gate compiles all reconstructed surfaces, runs the focused current-main regression plus existing Mission Control and Evidence Retrieval regressions, asserts governance invariants, checks that document scope cannot cross-match revision/parent namespaces, runs Ruff, and checks diff hygiene.

Repository-wide GitHub-hosted Actions remain affected by canonical incident #481, where private-repository jobs can fail before step 1 with `steps=null`. Such a run is infrastructure evidence only and is not treated as a code pass or failure.

## Supersession

This current-main v2 reconstruction is the authoritative continuation path for the Ask Calyx conversation capability. Once its exact-head comparison and CI status are recorded, the older #714 branch should remain unmerged and be closed as superseded rather than revived through stale ancestry.
