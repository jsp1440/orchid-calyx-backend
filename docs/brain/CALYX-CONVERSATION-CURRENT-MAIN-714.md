# CALYX Conversation Current-Main Reconstruction 714 v3

Status: MERGED TO CANONICAL MAIN / PRODUCTION MIGRATION AND DEPLOYMENT NOT AUTHORIZED

## Canonical merge

PR: `#798` — `CALYX-CONV v3 — current-main governed Ask Continuum conversations`.

Authorized pre-merge head: `2b27ca0a473fc03c419912d70b6cf4ca52da9c7a`.

Final validated pre-merge head after failure-first review corrections: `5b6a0ca05ef4e3130c5998a01678f393e540d160`.

Squash-merged to `main` on 2026-08-09 at `2026-08-09T19:09:30Z`.

Resulting canonical merge SHA: `3c93b4a9f296762bb93582968bab1e7b9618f664`.

PR #743 remains closed unmerged as superseded stale ancestry. BUILD-616R corrective publication-safety PR #795 was already merged before this integration; CALYX-CONV introduces no competing publication path.

## Final pre-merge validation

The exact final pre-merge head `5b6a0ca05ef4e3130c5998a01678f393e540d160` passed all applicable executable workflows:

- `CALYX Conversation Current Main 714` run `31330758029` — success;
- `CALYX-MISSION-CONTROL-003B Chat API` run `31330758057` — success;
- `CALYX-MISSION-CONTROL-003C Live Registration` run `31330758050` — success;
- `BUILD-088E Validation` run `31330758073` — success;
- `CALYX Workflow Governance Audit` run `31330758059` — success;
- `CALYX-SUPERVISED-PILOT-001` run `31330758028` — success;
- `CALYX Harvester Command 455` run `31330758097` — success;
- `CALYX-AUTONOMY-DEPLOYMENT-001` run `31330758053` — success.

The dedicated conversation gate passed compile/static checks, `24/24` focused conversation/Mission Control/Evidence Retrieval regressions, permanent governance assertions, Ruff lint, Ruff format, and diff hygiene.

Immediately before merge, three new P1 review findings were resolved and revalidated:

1. Authenticated Ask Continuum exchanges no longer copy research questions/answers into the unauthenticated legacy process-global transcript; response metadata is produced through an ephemeral private `GovernedOperatorChat` instance.
2. The governed conversation-source project-link router is mounted in the deployed `live_mission_control` router tree, not only in the registration helper used by tests.
3. Source-to-project linking now fails closed with `CONVERSATION_SOURCE_PROJECT_LINK_IDENTITY_CONFLICT` when an existing project link does not preserve the persisted source's exact document/revision identity.

Regression coverage for all three findings is included in the 24-test focused gate. All review threads were resolved before merge.

## Post-merge canonical verification

Canonical `main` at merge SHA `3c93b4a9f296762bb93582968bab1e7b9618f664` contains:

- private authenticated Ask exchange handling that does not write to the legacy global transcript;
- deployed Mission Control mounting of the governed source-link router;
- exact project-link document/revision identity verification;
- the CALYX conversation runtime, persistence models/services, report export, exact document scoping, read-only Knowledge Graph adapter, tests, and migration 140 definition.

The GitHub commit-status endpoint exposes no direct status contexts on the squash merge SHA. Therefore the strongest executable integration evidence is the immediately preceding green PR merge-ref workflow set against the same current `main`, supplemented by direct canonical-file verification after merge.

## Delivered API and authority boundaries

The canonical code provides:

- `POST /brain/mission-control/chat/ask`;
- owner-scoped persistent conversation create/list/get operations;
- `POST /brain/mission-control/chat/conversations/{conversation_id}/ask`;
- `GET /brain/mission-control/chat/conversations/{conversation_id}/report`;
- `POST /brain/mission-control/chat/conversations/{conversation_id}/sources/{result_id}/project-link`.

Conversation history remains `CONVERSATION_CONTEXT`, not scientific evidence. Prior conversation text is not evidence-retrieval authority. Model-memory evidence fallback is disabled. Knowledge Graph access is read-only. Scientific publication and Knowledge Graph mutation remain unauthorized. Source-to-project linking preserves exact persisted provenance and does not promote, approve, publish, canonize, or alter review/verification state.

Active-document retrieval scope accepts only canonical document namespaces (`metadata.document_id` and `metadata.source_document_id`). Revision IDs and parent IDs cannot silently satisfy document scope.

## Migration and deployment status

Migration `140_calyx_conversation_sessions.sql` is present in canonical `main` as a forward migration definition.

Migration 140 has **NOT been applied to production**.

Production deployment of the persistent-conversation capability has **NOT been performed by this merge cycle**.

No production database mutation, production Knowledge Graph mutation, scientific publication, Candidate Knowledge promotion, taxonomy activation, or external scientific communication is authorized or performed by this merge.

## Remaining release dependencies

Production use of persistent conversations requires a separate governed release decision after migration-140 release-readiness review. That review must establish production-schema prerequisites, transactional/rollback behavior, re-run safety, application ordering, smoke tests, observability, and abort criteria. Code merge alone does not authorize those actions.
