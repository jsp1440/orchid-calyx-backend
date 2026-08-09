# CALYX-470A — Unified owner flow on current main

Status: IMPLEMENTED / VALIDATION PENDING

## Purpose

Rebuild the useful owner-experience facade from stale PR #637 directly on current `main` without carrying its 173-commit-old history.

## Delivered

- One bounded owner-guided `Laelia anceps` demonstration mission using the current Brain mission service and durable Reasoning Ledger handoff.
- Operator status exposes mission plan, evidence, contradictions, gaps, confidence, blockers, validation state, durable ledger state, eligible-publication state, and Calyx Core certification summary without private chain-of-thought.
- Review derives authenticated reviewer identity and the current durable ledger version on the server.
- Publication-candidate discovery derives the exact current ledger ID, version, and review-content hash through the owner-scoped eligibility service; the owner does not copy hashes, IDs, workflow names, or server paths.
- Supervised publication checks `explicit_owner_confirmation=true` before discovery or publication-service invocation.
- Duplicate replay is surfaced explicitly as `NO_OP_DUPLICATE_REPLAY`.
- Graph version and audit outcome are shown only when returned by the governed publication gate; the facade never invents them.
- Focused browser/API regressions cover start, status, review, candidate discovery, confirmation gating, publication invocation, and duplicate replay.

## Governance

Automatic scientific approval and automatic publication remain disabled. A real production publication, deployment, taxonomy activation, credential change, schema mutation, or uncontrolled production Knowledge Graph mutation is outside this implementation and remains a separate explicit owner decision.

## Integration

This is a thin facade over the authoritative services already on `main`: Brain mission execution, durable Reasoning Ledger, owner-scoped eligibility discovery, supervised publication, and Calyx Core certification. It does not introduce parallel mission, review, publication, or graph-version stores.

## Validation gate

Merge only after the exact unchanged head passes:

- CALYX Unified Owner Flow 470A;
- CALYX-CORE-REBASE-004 Validation;
- BUILD-088E Validation;
- any additional workflow triggered by the shared Calyx Core router.

Update this record with the exact validated head and merge commit after completion.
