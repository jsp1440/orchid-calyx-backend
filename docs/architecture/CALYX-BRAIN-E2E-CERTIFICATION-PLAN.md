# CALYX-BRAIN-E2E — Governed reasoning-to-graph certification

## Purpose

Certify the canonical current-`main` pathway from reviewable evidence through deterministic inference, immutable Reasoning Ledger governance, exact human approval, and controlled Knowledge Graph publication.

This slice closes the remaining verification requirement in issue #191. It must not introduce an alternate ledger, graph, connector registry, publication gate, review system, or scientific authority.

## Required migration order

The disposable PostgreSQL 16 workflow must apply and validate migrations in this exact order:

1. 087B
2. 088B
3. 088C
4. 088D
5. 101
6. 103
7. 104
8. 105

Reapplication must verify idempotency only where explicitly promised. Rollback testing must remain isolated to the disposable test database.

## End-to-end proof

The certification must demonstrate:

1. Canonical Literature Intelligence or Candidate Knowledge evidence is available with stable identifiers, citations, source hashes, and provenance.
2. Deterministic inference is generated with a stable rule ID, rule version, evidence references, and deterministic content identity.
3. Submission creates exactly one immutable Reasoning Ledger revision and one corresponding audit event.
4. Human review is bound to the exact ledger version and exact review-content hash.
5. Any ledger-changing revision invalidates the prior approval.
6. Only a currently eligible and currently approved ledger version may enter the controlled publication adapter.
7. Publication delegates through the canonical BUILD-088 path and performs one atomic, provenance-complete graph transaction.
8. Rejected, superseded, withdrawn, and retracted outcomes remain append-only and auditable.
9. Private chain-of-thought fields and unapproved outreach or marketing data are rejected before scientific publication.
10. Research Station and Species Dossier consumers resolve canonical identifiers without creating duplicate authority.

## Negative-path requirements

The workflow must explicitly test:

- stale expected ledger version;
- stale review-content hash;
- approval invalidated after revision;
- missing or changed literature source hash;
- ambiguous or missing canonical graph identity;
- duplicate inference submission;
- duplicate publication submission;
- rejected publication gate outcome;
- tenant or project isolation violation;
- private-reasoning field injection;
- outreach-data publication attempt;
- supersession, withdrawal, and retraction lifecycle audit retention.

## Allowed changes

- One focused PostgreSQL 16 end-to-end test module.
- One dedicated GitHub Actions workflow.
- Narrow integration corrections proven necessary by the test.
- Documentation of exact evidence, limitations, rollback behavior, and final result.

## Guardrails

- Keep the pull request draft until latest-head CI is green and evidence has been independently inspected.
- No automatic merge.
- No production migration or deployment.
- No production data mutation.
- No direct graph SQL outside the canonical controlled graph repository.
- No automatic approval or publication.
- No persistence of private chain-of-thought.
- No claim of completion from local tests alone.

## Acceptance criteria

- Latest-head dedicated PostgreSQL 16 workflow passes.
- Migration order and rollback isolation are proven.
- The full governed chain and all required negative paths pass.
- Graph provenance and lifecycle audit records are inspected and documented.
- Existing Reasoning Ledger, Brain integration, Candidate Knowledge, Literature Intelligence, Knowledge Graph, Research Station, and Species Dossier behavior remains compatible.
- Issue #191 is updated with exact workflow run, commit SHA, test counts, limitations, and final completion recommendation.
