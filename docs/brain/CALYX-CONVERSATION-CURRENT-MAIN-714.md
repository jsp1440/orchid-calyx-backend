# CALYX Conversation Current-Main Reconstruction 714 v3

Status: RECONSTRUCTED ON CURRENT MAIN / EXECUTABLE VALIDATION REQUIRED

## Purpose

Reconstruct the governed Ask Calyx conversation stack directly on the current `main` lineage. Historical PR #743 is source material only because it diverged to 15 commits ahead and 66 commits behind current main before this reconstruction.

## Delivered

- Retrieval-grounded `POST /brain/mission-control/chat/ask` with no general-model evidence fallback.
- Optional active taxon context through a bounded, read-only Knowledge Graph traversal adapter.
- Owner-scoped persistent research conversation sessions and append-only messages.
- Exact active-document scoping through Evidence Retrieval.
- Canonical source-document identity preservation in citations and persisted source references.
- Markdown conversation reports with a deduplicated source ledger and explicit non-evidence boundary.
- Owner-scoped source-to-project linking that derives project/document/revision identity from persisted conversation provenance rather than caller-supplied authority fields.
- Mission Control registration for both chat and source-link routers.
- Forward-only migration `140_calyx_conversation_sessions.sql`, included as code but not applied to production.
- Focused current-main regressions and dedicated read-only CI.

## Reconstruction discipline

The v3 branch was created from current `main`. Conversation-specific additive files were carried forward from reviewed PR #743. Shared files were reconciled against their current-main versions rather than copied wholesale, preserving intervening Calyx and Brain changes.

Only canonical document namespaces may satisfy active-document scope: `metadata.document_id` and `metadata.source_document_id`. Revision IDs and parent IDs remain separate namespaces and must not cross-match document scope.

## Evidence and publication governance

Conversation history is `CONVERSATION_CONTEXT`, not scientific evidence. Prior conversation text is not fed back as evidence retrieval authority. Model-memory evidence authority is disabled. Knowledge Graph access is read-only. Scientific publication and Knowledge Graph mutation remain unauthorized.

Saving a persisted source to a Research Workspace project preserves its exact `result_id` and citation document/revision identity; it does not promote, approve, publish, or canonize the source.

The migration constrains persisted messages to `evidence_authority=false`, `scientific_publication_authorized=false`, and `knowledge_graph_mutation_authorized=false`, and installs an append-only update/delete guard.

No production migration, deployment, scientific publication, taxonomy activation, credential change, Candidate Knowledge promotion, or production Knowledge Graph mutation is authorized by this build.

## Validation

Dedicated workflow: `CALYX Conversation Current Main 714`.

The executable gate compiles reconstructed surfaces, runs focused conversation, Mission Control, and Evidence Retrieval regressions, checks governance invariants and document-namespace isolation, then runs Ruff lint/format and diff hygiene.

The v3 branch remains validation-pending until its exact current head receives executable CI. Historical #743 runner failures are not used as validation evidence.

## Supersession

Once v3 exact-head validation succeeds, the new v3 PR becomes the authoritative continuation path and PR #743 should remain unmerged/closed as superseded stale ancestry.
