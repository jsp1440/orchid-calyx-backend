# CALYX-470A — Unified owner flow on current main

Status: IMPLEMENTED / VALIDATION PENDING

## Purpose

Rebuild the useful owner-experience facade from stale PR #637 directly on current `main` without carrying its 173-commit-old history.

## Delivered

- One bounded owner-guided `Laelia anceps` demonstration mission using the current Research Workspace, Brain mission service, and durable Reasoning Ledger handoff.
- Before Brain execution, the server resolves a canonical owner-scoped Research Workspace project. A supplied project must already exist and belong to the authenticated owner; with no supplied project, the flow reuses the owner's active bounded `Laelia anceps` demo workspace or creates one through the authoritative Research Workspace service. The owner never copies a project UUID.
- Project resolution happens before mission execution, preventing a mission from completing in memory and then failing only at durable Reasoning Ledger handoff because of an invalid/nonexistent project.
- Operator status exposes mission plan, evidence, contradictions, gaps, confidence, blockers, validation state, durable ledger state, eligible-publication state, and Calyx Core certification summary without private chain-of-thought.
- Review derives authenticated reviewer identity and the current durable ledger version on the server.
- Publication-candidate discovery derives the exact current ledger ID, version, and review-content hash through the owner-scoped eligibility service; the owner does not copy hashes, IDs, workflow names, or server paths.
- Supervised publication checks `explicit_owner_confirmation=true` before discovery or publication-service invocation.
- Duplicate replay is surfaced explicitly as `NO_OP_DUPLICATE_REPLAY`.
- Publication result semantics are derived from the authoritative publication artifact, not merely the service's `created` flag. A governed Knowledge Graph gate rejection is reported as `PUBLICATION_REJECTED`; it is never mislabeled `PUBLISHED`.
- Graph version and audit outcome are shown only when returned by the governed publication gate; the facade never invents them.
- Focused browser/API regressions cover start, canonical workspace resolution at the API boundary, status, review, candidate discovery, confirmation gating, successful publication projection, governed publication rejection, and duplicate replay.

## Governance

Automatic scientific approval and automatic publication remain disabled. A real production publication, deployment, taxonomy activation, credential change, schema mutation, or uncontrolled production Knowledge Graph mutation is outside this implementation and remains a separate explicit owner decision.

The publication endpoint may call the existing governed publication service only after explicit owner confirmation and fresh owner-scoped eligibility discovery. Tests replace the production gate/service and do not perform a real graph publication.

## Integration

This is a thin facade over authoritative services already on `main`: Research Workspace, Brain mission execution, durable Reasoning Ledger, owner-scoped eligibility discovery, supervised publication, and Calyx Core certification. It does not introduce parallel project, mission, review, publication, or graph-version stores.

## Static compatibility findings resolved

During current-main reconciliation two stale-branch defects were found and corrected before merge:

1. The old default project identifier `laelia-anceps-demonstration` was not a valid Research Workspace UUID and could allow Brain execution to run before durable ledger handoff failed. CALYX-470A resolves or creates the canonical project first.
2. `ReasoningLedgerPublicationService.publish()` can return a newly recorded `rejected` artifact when the governed graph gate rejects publication. CALYX-470A distinguishes `PUBLISHED`, `PUBLICATION_REJECTED`, `PUBLICATION_NOT_COMPLETED`, and `NO_OP_DUPLICATE_REPLAY` rather than treating every newly created artifact as a successful publication.

## Validation gate

Merge only after the exact unchanged head passes real executable jobs for:

- CALYX Unified Owner Flow 470A;
- CALYX-CORE-REBASE-004 Validation;
- BUILD-088E Validation;
- every additional workflow triggered by the shared Calyx Core router.

A GitHub Actions job with no executed steps is infrastructure evidence only and does not satisfy this gate.

Update this record with the exact validated head and merge commit after completion.
