# CALYX Conversation Current-Main Reconstruction 714

Status: IMPLEMENTED / EXECUTABLE CI BLOCKED BY #481

## Purpose

Reconstruct the useful Ask Calyx conversation stack directly on current `main` instead of attempting to merge the stale 91-commit #634 → #640 ancestry, which is 175 commits behind current `main` and conflicts with the present repository.

## Delivered

- Retrieval-grounded `POST /brain/mission-control/chat/ask` with no general-model evidence fallback.
- Optional active taxon context through a bounded, read-only Knowledge Graph traversal adapter.
- Owner-scoped persistent research conversation sessions and append-only messages.
- Exact active-document scoping through Evidence Retrieval.
- Canonical source-document identity preservation in citations and persisted source references.
- Markdown conversation reports with a deduplicated source ledger and explicit non-evidence boundary.
- Owner-scoped `Save source to project` action that resolves project/document/revision identity from persisted conversation provenance rather than caller-supplied IDs.
- Current Mission Control registration for both the chat and source-link routers.
- Forward-only migration `140_calyx_conversation_sessions.sql`; it is included but not applied to production.
- Focused current-main regression test and dedicated read-only CI workflow.

## Important corrective change from the stale stack

The old stacked head used active-document matching across four namespaces: document ID, source-document ID, revision ID, and parent ID. That is unsafe because revision and parent identifiers are independent namespaces and can collide with a document identifier. This reconstruction intentionally matches only `metadata.document_id` and `metadata.source_document_id`.

The regression suite includes both a positive canonical document-ID match and negative revision/parent collision checks. The workflow also statically rejects any reintroduction of revision/parent matching into the document-scope gate.

## Dependency reduction

The old CALYX-640 branch inherited unrelated scientific-analysis, Research Station, literature-acquisition, and dataset-row files from its historical stack. This reconstruction does not carry those files forward merely because they were ancestors. It depends only on services already present on current `main` plus the conversation-specific surfaces delivered here.

This keeps the current-main delta bounded to the actual conversation capability instead of attempting to merge roughly 9,400 stale-stack additions.

## Governance

Conversation history is `CONVERSATION_CONTEXT`, not scientific evidence. Model-memory evidence authority is disabled. Knowledge Graph access is read-only. Scientific publication and Knowledge Graph mutation remain unauthorized. Saving a source to a Research Workspace project does not elevate that source to published or canonical knowledge.

No production migration, deployment, scientific publication, taxonomy activation, or Knowledge Graph mutation is authorized by this build.

## Validation

Dedicated workflow: `CALYX Conversation Current Main 714`.

The intended executable gate compiles all reconstructed surfaces, runs the focused current-main regression plus existing Mission Control/Evidence Retrieval regressions, asserts governance invariants, checks that document scope cannot cross-match revision/parent namespaces, runs Ruff, and checks diff hygiene.

GitHub-hosted Actions are currently failing before step 1 with `steps=null` under canonical incident #481, so no executable CI verdict is claimed until a runner actually starts. Static review and repository-diff inspection are not substitutes for that gate.

## Stale-stack disposition

Audit PR #713 proves the full inherited CALYX-640 stack is not a safe merge candidate against current `main`: GitHub reports it non-mergeable, 91 commits ahead / 175 behind, with 67 changed files and about 9,400 additions. This current-main reconstruction is the intended replacement path; old stacked PRs should be closed only after this replacement is reviewed and no unique required behavior is found missing.
