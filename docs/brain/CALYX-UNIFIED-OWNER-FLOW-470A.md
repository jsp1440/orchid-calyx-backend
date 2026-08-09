# CALYX-470A/470B — Unified owner flow on current main

Status: IMPLEMENTED / EXECUTABLE-GREEN / READY FOR OWNER REVIEW

Executable-green code head: `75471fa9aff746b42e871511e2236adf3f7e0bb2`.

## Purpose

Rebuild the useful owner-experience facade from stale history directly on current `main` without carrying unrelated or obsolete commits. CALYX-470B is the authoritative current-main reconstruction of the reviewed CALYX-470A implementation.

## Delivered

- One bounded owner-guided `Laelia anceps` demonstration mission using the current Research Workspace, Brain mission service, and durable Reasoning Ledger handoff.
- Before Brain execution, the server resolves a canonical owner-scoped Research Workspace project. A supplied project must already exist and belong to the authenticated owner; with no supplied project, the flow reuses the owner's active bounded `Laelia anceps` demo workspace or creates one through the authoritative Research Workspace service. The owner never copies a project UUID.
- Project resolution happens before mission execution, preventing a mission from completing in memory and then failing only at durable Reasoning Ledger handoff because of an invalid/nonexistent project.
- Operator status exposes mission plan, evidence, contradictions, gaps, confidence, blockers, validation state, durable ledger state, eligible-publication state, and Calyx Core certification summary without private chain-of-thought.
- Mutable review-facing mission fields are reconciled from the durable Reasoning Ledger and current eligibility discovery. A stale in-memory mission snapshot cannot continue to report `HUMAN_REVIEW_REQUIRED`, an old ledger version, or `eligible=false` after the durable ledger has been reviewed and become eligible.
- Displayed review state is bound to the **current durable ledger version and `review_content_hash`**. Historical approvals from an older ledger version/hash are ignored for current status and the mission returns to `HUMAN_REVIEW_REQUIRED` until the current content is reviewed.
- Review derives authenticated reviewer identity and the current durable ledger version on the server.
- Publication-candidate discovery derives the exact current ledger ID, version, and review-content hash through the owner-scoped eligibility service; the owner does not copy hashes, IDs, workflow names, or server paths.
- Supervised publication checks `explicit_owner_confirmation=true` before discovery or publication-service invocation.
- Duplicate replay is surfaced explicitly as `NO_OP_DUPLICATE_REPLAY`.
- Publication result semantics derive from the authoritative publication artifact. A governed Knowledge Graph gate rejection is reported as `PUBLICATION_REJECTED`; it is never mislabeled `PUBLISHED`.
- Graph version and audit outcome are shown only when returned by the governed publication gate; the facade never invents them.
- Focused browser/API regressions cover start, canonical workspace reuse/create/validation, status, durable review-state reconciliation, stale-approval invalidation, review, candidate discovery, confirmation gating, successful publication projection, governed publication rejection, and duplicate replay.

## CALYX-470B current-main reconstruction

The reviewed additive CALYX-470A files were reconstructed onto current `main` rather than rebasing the historical branch. Shared `app/routers/calyx_core.py` was edited against current main instead of copied wholesale, preserving unrelated current-main routes.

Static governance review found and corrected a stale-approval projection defect: durable review decisions are filtered to the exact current ledger `version` plus `review_content_hash` before displaying a review outcome. An approval for version N/hash A is not displayed as current after the ledger becomes version N+1/hash B.

## Governance

Automatic scientific approval and automatic publication remain disabled. A real production publication, deployment, taxonomy activation, credential change, schema mutation, or uncontrolled production Knowledge Graph mutation is outside this implementation and remains a separate explicit owner decision.

The publication endpoint may call the existing governed publication service only after explicit owner confirmation and fresh owner-scoped eligibility discovery. Tests replace the production gate/service and do not perform a real graph publication.

Parent epic #384 states that agents open PRs and stop before merge. Therefore executable validation permits review readiness, not merge or production publication.

## Integration

This is a thin facade over authoritative services already in Calyx Core: Research Workspace, Brain mission execution, durable Reasoning Ledger, owner-scoped eligibility discovery, supervised publication, and Calyx Core certification. It introduces no parallel project, mission, review, publication, or graph-version store.

The Brain mission remains authoritative for bounded scientific evidence and interpretation output. The durable SQL Reasoning Ledger is authoritative for mutable human review state and ledger version. Eligibility discovery is authoritative for whether the current reviewed ledger may proceed to the explicit-confirmation publication gate.

## Compatibility findings resolved

1. The historical default project identifier was not a valid Research Workspace UUID; canonical project resolution now occurs before mission execution.
2. Governed graph-gate rejection is distinguished from successful publication and incomplete publication.
3. Operator status overlays mutable review/eligibility state from durable authority rather than stale in-memory mission fields.
4. Displayed approval is accepted only when bound to the current durable ledger version and content hash.
5. Recovered executable CI found one final Ruff import-organization issue in `app/routers/calyx_unified_owner_flow.py`; the service import was wrapped according to Ruff without behavioral or governance changes.

Duplicate replay was re-audited against `ReasoningLedgerPublicationService`: `created=False` is limited to an already-published persisted artifact, so `NO_OP_DUPLICATE_REPLAY` remains correctly limited to a previously published exact artifact.

## Executable validation

Exact code head `75471fa9aff746b42e871511e2236adf3f7e0bb2` is green across all six applicable workflows:

- CALYX Unified Owner Flow 470A run `31323832649` — success;
- CALYX Workflow Governance Audit `31323832655` — success;
- CALYX-CORE-REBASE-002A `31323832648` — success;
- CALYX-CORE-REBASE-004 `31323832633` — success;
- BUILD-088E Validation `31323832631` — success;
- Calyx Conversation Validation `31323832646` — success.

The dedicated owner-flow gate passed:

- compile;
- 23 unified-owner-flow and existing operator regressions;
- permanent supervised-publication governance assertions;
- changed-surface Ruff;
- diff hygiene.

No unresolved review threads exist on PR #737.

## Remaining boundary

The implementation is ready for review, but merge and any real publication remain owner-governed. No production publication, canonical Knowledge Graph mutation, taxonomy activation, deployment, credential change, or schema mutation was performed during validation.
