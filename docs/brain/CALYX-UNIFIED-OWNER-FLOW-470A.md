# CALYX-470A/470B — Unified owner flow on current main

Status: IMPLEMENTED / EXECUTABLE VALIDATION PENDING

## Purpose

Rebuild the useful owner-experience facade from stale history directly on current `main` without carrying unrelated or obsolete commits. CALYX-470B is the authoritative current-main reconstruction of the reviewed CALYX-470A implementation.

## Delivered

- One bounded owner-guided `Laelia anceps` demonstration mission using the current Research Workspace, Brain mission service, and durable Reasoning Ledger handoff.
- Before Brain execution, the server resolves a canonical owner-scoped Research Workspace project. A supplied project must already exist and belong to the authenticated owner; with no supplied project, the flow reuses the owner's active bounded `Laelia anceps` demo workspace or creates one through the authoritative Research Workspace service. The owner never copies a project UUID.
- Project resolution happens before mission execution, preventing a mission from completing in memory and then failing only at durable Reasoning Ledger handoff because of an invalid/nonexistent project.
- Operator status exposes mission plan, evidence, contradictions, gaps, confidence, blockers, validation state, durable ledger state, eligible-publication state, and Calyx Core certification summary without private chain-of-thought.
- Mutable review-facing mission fields are reconciled from the durable Reasoning Ledger and current eligibility discovery. A stale in-memory mission snapshot cannot continue to report `HUMAN_REVIEW_REQUIRED`, an old ledger version, or `eligible=false` after the durable ledger has been reviewed and become eligible.
- Review derives authenticated reviewer identity and the current durable ledger version on the server.
- Publication-candidate discovery derives the exact current ledger ID, version, and review-content hash through the owner-scoped eligibility service; the owner does not copy hashes, IDs, workflow names, or server paths.
- Supervised publication checks `explicit_owner_confirmation=true` before discovery or publication-service invocation.
- Duplicate replay is surfaced explicitly as `NO_OP_DUPLICATE_REPLAY`.
- Publication result semantics are derived from the authoritative publication artifact, not merely the service's `created` flag. A governed Knowledge Graph gate rejection is reported as `PUBLICATION_REJECTED`; it is never mislabeled `PUBLISHED`.
- Graph version and audit outcome are shown only when returned by the governed publication gate; the facade never invents them.
- Focused browser/API regressions cover start, canonical workspace reuse/create/validation, status, durable review-state reconciliation, review, candidate discovery, confirmation gating, successful publication projection, governed publication rejection, and duplicate replay.

## CALYX-470B current-main reconstruction

On 2026-08-08 the reviewed additive files from CALYX-470A were reconstructed onto exact current `main` parent `7f5bec2fb8092739a8e5fc5ce55ebc9008a9171e` instead of rebasing the 17-commit historical branch.

The following reviewed blobs were reused byte-for-byte:

- `app/routers/calyx_unified_owner_flow.py` — `e2a4d57ea3e3de42999cc0cbb9a2f4e40f92c7f4`
- `tests/test_calyx_unified_owner_flow_470.py` — `301544e23688b5cbbcf9faf0a63bc28e8b23c9e7`
- `tests/test_calyx_unified_owner_flow_470_reconciliation.py` — `78893af495d49cc2986ef90a619a86184ffc7c26`
- `tests/test_calyx_unified_owner_flow_470_rejection.py` — `6a8c9a5e6c2e495140dbecbca456e61248b53641`
- `tests/test_calyx_unified_owner_flow_470_workspace.py` — `05f056ba34534f9f2830e607b7dfb1a2b459b0a3`
- `.github/workflows/calyx-unified-owner-flow-470a.yml` — `915dd7540dc13c289dfe2da53641ed763732d9b6`

The shared `app/routers/calyx_core.py` was **not** copied from the old branch. It was edited against current `main`, and the final compare shows exactly two added lines: the unified-owner-flow router import and include. An intermediate accidental `ShowCreate` request-type regression was detected before PR creation, repaired, and the subsequent `main` comparison confirmed zero unrelated router deletions or modifications.

## Governance

Automatic scientific approval and automatic publication remain disabled. A real production publication, deployment, taxonomy activation, credential change, schema mutation, or uncontrolled production Knowledge Graph mutation is outside this implementation and remains a separate explicit owner decision.

The publication endpoint may call the existing governed publication service only after explicit owner confirmation and fresh owner-scoped eligibility discovery. Tests replace the production gate/service and do not perform a real graph publication.

Parent epic #384 additionally states that agents open PRs and stop before merge. Therefore this reconstruction remains draft/unmerged unless the owner explicitly authorizes its merge after exact-head executable validation.

## Integration

This is a thin facade over authoritative services already on `main`: Research Workspace, Brain mission execution, durable Reasoning Ledger, owner-scoped eligibility discovery, supervised publication, and Calyx Core certification. It does not introduce parallel project, mission, review, publication, or graph-version stores.

The Brain mission remains authoritative for bounded scientific evidence and interpretation output. The durable SQL Reasoning Ledger is authoritative for mutable human review state and ledger version. Eligibility discovery is authoritative for whether the current reviewed ledger may proceed to the explicit-confirmation publication gate.

## Static compatibility findings resolved

During current-main reconciliation three stale-branch defects were found and corrected before the original CALYX-470A freeze:

1. The old default project identifier `laelia-anceps-demonstration` was not a valid Research Workspace UUID and could allow Brain execution to run before durable ledger handoff failed. CALYX-470A resolves or creates the canonical project first.
2. `ReasoningLedgerPublicationService.publish()` can return a newly recorded `rejected` artifact when the governed graph gate rejects publication. CALYX-470A distinguishes `PUBLISHED`, `PUBLICATION_REJECTED`, `PUBLICATION_NOT_COMPLETED`, and `NO_OP_DUPLICATE_REPLAY` rather than treating every newly created artifact as a successful publication.
3. The in-memory Brain mission snapshot is intentionally not mutated by durable ledger review. CALYX-470A therefore overlays review status, durable ledger version, and publication eligibility from the durable ledger/current eligibility when producing the operator view, preventing contradictory post-review instructions.

The in-memory and operational Reasoning Ledger services both derive ledger identity through the same deterministic `(tenant, project, title)` identity function, so the current-main durable handoff preserves ledger identity after canonical project resolution.

## Validation gate

Merge only after the exact unchanged CALYX-470B head passes real executable jobs for:

- CALYX Unified Owner Flow 470A;
- CALYX-CORE-REBASE-004 Validation;
- BUILD-088E Validation;
- every additional workflow triggered by the shared Calyx Core router.

A GitHub Actions job with no executed steps is infrastructure evidence only and does not satisfy this gate. Issue #481 remains the canonical hosted-runner blocker if jobs return `steps=null`.

Update this record with the exact validated head and merge commit after completion.
