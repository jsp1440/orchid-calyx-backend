# CALYX-470 — Unified owner operator flow from mission to supervised publication

Status: IMPLEMENTED / VALIDATION PENDING / GOVERNED SUPERVISED FLOW

## Delivered

- One bounded owner-guided `Laelia anceps` demonstration flow using the existing Brain mission service and durable Reasoning Ledger handoff.
- Operator status payload includes mission plan, evidence, supporting evidence, contradictions, evidence gaps, confidence, blockers, validation state, full durable Reasoning Ledger, eligible-publication state, and production certification summary.
- Review endpoint derives the current ledger/version and reviewer identity on the server; the owner selects only approve, request revision, reject, or defer plus rationale.
- Publication-candidate endpoint automatically discovers the mission's eligible reviewed ledger through the existing owner-scoped read-only eligibility service.
- Supervised publication endpoint accepts only explicit owner confirmation plus an optional note. Ledger ID, current version, and exact review-content hash are discovered server-side, so the owner never copies hashes, IDs, workflow names, or server paths.
- Publication service is invoked at most once per request and only after explicit confirmation and current eligibility discovery.
- Publication response exposes graph version when returned by the governed publication gate, audit outcome when returned, and an explicit `NO_OP_DUPLICATE_REPLAY` result when the exact artifact was already published.
- Plain-language status/error messages accompany machine-readable codes.
- Browser/API contract tests cover start → scientific state → ledger → review → automatic candidate discovery → confirmation gate → one supervised publication → duplicate replay no-op.

## Integration model

CALYX-470 does not create a second mission, review, eligibility, publication, or Knowledge Graph implementation. It is a thin owner-experience facade over the authoritative services already merged through CALYX-CORE-REBASE-004 (#565) and production certification v3 (#590).

The bounded demonstration question is fixed to taxonomy, distribution, pollination, conservation, and mycorrhizal evidence for `Laelia anceps`. The flow returns the scientific evidence state that the Brain mission actually produced; missing evidence and contradictions remain visible rather than being filled in.

## Governance boundaries

Scientific review remains a human decision. Publication is impossible without `explicit_owner_confirmation=true`, and the publication service is not even reached before that check passes. Eligibility is rediscovered at publication time so stale client-supplied versions or hashes cannot authorize publication.

This implementation does not execute a real production publication, deploy code, activate taxonomy, rotate credentials, alter production schemas, or mutate the production Knowledge Graph from tests. A real supervised production publication remains a separate explicit owner decision.

## Validation

Dedicated CI compiles the new owner-flow surface, runs CALYX-470 tests plus the existing CALYX-CORE-REBASE-004 operator regressions, asserts permanent confirmation/no-auto-publication/no-ID-copying boundaries, runs Ruff on the new surface, and checks diff hygiene. Record exact-head evidence here after validation completes.
