# CALYX Conversation Current-Main Reconstruction 714 v3

Status: VALIDATED ON PR #798 / READY FOR REVIEW

## Purpose

Reconstruct the governed Ask Calyx conversation stack directly on the current `main` lineage. Historical PR #743 is source material only because it diverged to 15 commits ahead and 66 commits behind current main before this reconstruction.

## Exact validated implementation

PR: `#798` — `CALYX-CONV v3 — current-main governed Ask Continuum conversations`.

Exact implementation head validated on 2026-08-09: `f8abc1423fbddb4e8030affccfb55d0a62a78f59`.

Validation on that exact implementation head:

- `CALYX Conversation Current Main 714` run `31329939437` — success. Compile, focused conversation/Mission Control/Evidence Retrieval regressions, governance assertions, Ruff lint, Ruff format, and diff hygiene all passed.
- Focused regression set — `21/21` passing.
- `CALYX-MISSION-CONTROL-003B Chat API` run `31329939470` — success after its reduced CI environment was aligned with the SQLAlchemy and psycopg runtime imports.
- `CALYX-MISSION-CONTROL-003C Live Registration` run `31329939469` — success after its reduced CI environment was aligned with the SQLAlchemy and psycopg runtime imports.
- `BUILD-088E Validation` run `31329939459` — success, including PostgreSQL publication-pipeline readiness and BUILD-088B through BUILD-088D isolated regression.
- `CALYX Workflow Governance Audit` run `31329939465` — success.
- PR #798 review-thread audit — no inline review threads present.

Earlier exact-head failures were resolved failure-first: Ruff formatting drift across the conversation surface, then reduced Mission Control workflow dependency gaps. No application behavior or authority boundary was weakened to obtain green CI.

The first Brain documentation head `d4e9d0dc48bfe46f381478fe3057df2c6118c9ff` also passed the same five exact-head workflows before PR #798 was promoted to ready-for-review and PR #743 was closed as superseded. This final checkpoint update only reconciles that now-completed state in the Brain; it introduces no runtime/API/schema behavior.

## Delivered

- Retrieval-grounded authenticated `POST /brain/mission-control/chat/ask` with no general-model evidence fallback.
- Optional active taxon context through a bounded, read-only Knowledge Graph traversal adapter.
- Owner-scoped persistent research conversation sessions and append-only messages.
- Exact active-document scoping through Evidence Retrieval.
- Canonical source-document identity preservation in citations and persisted source references.
- Markdown conversation reports rendered from persisted transcript/context without re-running scientific retrieval.
- Owner-scoped source-to-project linking that derives project/document/revision identity from persisted conversation provenance rather than caller-supplied authority fields.
- Mission Control registration for both chat and source-link routers.
- Forward-only migration `140_calyx_conversation_sessions.sql`, included as code but not applied to production.
- Focused current-main regressions and dedicated read-only CI.

## API and schema impact

The branch adds or reconstructs these governed Mission Control surfaces:

- `POST /brain/mission-control/chat/ask`;
- conversation create/list/get operations;
- `POST /brain/mission-control/chat/conversations/{conversation_id}/ask`;
- `GET /brain/mission-control/chat/conversations/{conversation_id}/report`;
- `POST /brain/mission-control/chat/conversations/{conversation_id}/sources/{result_id}/project-link`.

Persistence definitions add `research_station.conversation_sessions` and `research_station.conversation_messages`. Conversation messages are constrained as context-only, non-evidence, non-publication-authorizing, non-Knowledge-Graph-mutating records and are guarded against update/delete mutation.

## Document identity boundary

Only canonical document namespaces may satisfy active-document scope: `metadata.document_id` and `metadata.source_document_id`. Revision IDs and parent IDs remain separate namespaces and must not cross-match document scope.

Focused regressions explicitly verify positive canonical-document matching and negative revision-ID / parent-ID collision cases. CI also statically rejects reintroduction of revision/parent namespace matching into the document-scope gate.

## Evidence and publication governance

Conversation history is `CONVERSATION_CONTEXT`, not scientific evidence. Prior conversation text is not evidence-retrieval authority. Model-memory evidence authority is disabled. Knowledge Graph access is read-only. Scientific publication and Knowledge Graph mutation remain unauthorized.

Saving a persisted source to a Research Workspace project preserves exact persisted source identity and citation document/revision provenance; it does not promote, approve, publish, canonize, or alter the source's review/verification state.

BUILD-088E compatibility is green. The conversation stack does not add a publication adapter or competing publication path and does not bypass the canonical publication-control pipeline.

## Migration and deployment status

Migration `140_calyx_conversation_sessions.sql` is a forward-only migration definition present in the PR. It has **NOT been applied to production**.

Deployment status: **not deployed by this validation work**.

No production database mutation, production Knowledge Graph mutation, scientific publication, Candidate Knowledge promotion, taxonomy activation, credential change, or external scientific communication is authorized or performed by PR #798.

## Known limitations / remaining governed work

- Production use of persistent conversations depends on a separately governed migration/release process for migration 140.
- This build provides retrieval-grounded summaries and read-only graph context; it does not authorize model-memory evidence, new scientific interpretation as canonical knowledge, or publication.
- PR merge and deployment remain separate governed release actions.

## Supersession

PR #798 is the authoritative continuation path for this conversation capability and is ready for governed review. PR #743 is closed unmerged as superseded stale ancestry and must not be revived as a competing integration path.
