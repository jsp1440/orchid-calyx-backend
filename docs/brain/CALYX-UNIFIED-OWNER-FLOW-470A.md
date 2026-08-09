# CALYX-470A — Unified owner flow on current main

Status: IMPLEMENTED / VALIDATION PENDING

## Purpose

Rebuild the useful owner-experience facade from stale PR #637 directly on current `main` without carrying its 173-commit-old history.

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

## Governance

Automatic scientific approval and automatic publication remain disabled. A real production publication, deployment, taxonomy activation, credential change, schema mutation, or uncontrolled production Knowledge Graph mutation is outside this implementation and remains a separate explicit owner decision.

The publication endpoint may call the existing governed publication service only after explicit owner confirmation and fresh owner-scoped eligibility discovery. Tests replace the production gate/service and do not perform a real graph publication.

## Integration

This is a thin facade over authoritative services already on `main`: Research Workspace, Brain mission execution, durable Reasoning Ledger, owner-scoped eligibility discovery, supervised publication, and Calyx Core certification. It does not introduce parallel project, mission, review, publication, or graph-version stores.

The Brain mission remains authoritative for bounded scientific evidence and interpretation output. The durable SQL Reasoning Ledger is authoritative for mutable human review state and ledger version. Eligibility discovery is authoritative for whether the current reviewed ledger may proceed to the explicit-confirmation publication gate.

## Static compatibility findings resolved

During current-main reconciliation three stale-branch defects were found and corrected before merge:

1. The old default project identifier `laelia-anceps-demonstration` was not a valid Research Workspace UUID and could allow Brain execution to run before durable ledger handoff failed. CALYX-470A resolves or creates the canonical project first.
2. `ReasoningLedgerPublicationService.publish()` can return a newly recorded `rejected` artifact when the governed graph gate rejects publication. CALYX-470A distinguishes `PUBLISHED`, `PUBLICATION_REJECTED`, `PUBLICATION_NOT_COMPLETED`, and `NO_OP_DUPLICATE_REPLAY` rather than treating every newly created artifact as a successful publication.
3. The in-memory Brain mission snapshot is intentionally not mutated by durable ledger review. CALYX-470A therefore overlays review status, durable ledger version, and publication eligibility from the durable ledger/current eligibility when producing the operator view, preventing contradictory post-review instructions.

The in-memory and operational Reasoning Ledger services both derive ledger identity through the same deterministic `(tenant, project, title)` identity function, so the current-main durable handoff preserves ledger identity after canonical project resolution.

## Validation gate

Merge only after the exact unchanged head passes real executable jobs for:

- CALYX Unified Owner Flow 470A;
- CALYX-CORE-REBASE-004 Validation;
- BUILD-088E Validation;
- every additional workflow triggered by the shared Calyx Core router.

A GitHub Actions job with no executed steps is infrastructure evidence only and does not satisfy this gate.

Update this record with the exact validated head and merge commit after completion.
