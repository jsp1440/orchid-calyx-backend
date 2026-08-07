# CALYX-CORE-REBASE-004 — Current-main supervised operator workflow

## Purpose

Recover the useful operator experience from stale PR #403 without reviving its synthetic mission evidence, fake ledger-review store, fake publication store, or stale `app/main.py` changes.

## Authoritative integration

The operator facade is intentionally thin and delegates to current services:

- Brain scientific missions: `app.brain_mission.routes.SERVICE`
- durable Reasoning Ledger: `OperationalReasoningLedgerService`
- current-version eligible-ledger discovery: `app.reasoning_publication.eligibility.discover_eligible_ledgers`
- governed publication: `ReasoningLedgerPublicationService` + `ExistingKnowledgeGraphPublicationGate`
- operational readiness: `runtime.calyx_core_certification.build_calyx_core_certification`

The facade is mounted beneath the already-authoritative Calyx Core router at `/api/mission-control/calyx-operator`.

## Operator endpoints

- `POST /missions` starts the existing bounded Brain evidence mission with tenant and actor derived from authentication, then synchronizes the exact immutable mission-ledger snapshot into the durable operational Reasoning Ledger before returning the ledger ID.
- `GET /missions/{mission_id}` exposes a safe operator summary and hides cross-tenant mission existence.
- `GET /ledgers/eligible` uses the same current-version, owner-scoped eligibility query as the existing reasoning-publication API.
- `POST /ledgers/{ledger_id}/review` records a durable Reasoning Ledger review with reviewer identity derived from authentication.
- `POST /publications` requires `explicit_owner_confirmation=true`, an expected ledger version, and the exact current review-content hash before invoking the existing governed publication service.
- `GET /publications/{ledger_id}` returns owner-scoped publication history.
- `GET /graph/version` deliberately does not invent a graph version; it reports `graph_version: null` and current operational blockers.
- `GET /panel` combines optional mission state, eligible ledgers, and Calyx Core readiness without performing publication or graph mutation.

## Eligibility refactor

Eligible-ledger discovery was factored out of `app.reasoning_publication.routes` into `app.reasoning_publication.eligibility`. Both the existing API and the new Mission Control facade now use one implementation, preserving current-version review-hash binding and owner isolation.

## P1 review repair — durable mission-ledger handoff

Review identified a real integration defect in the start → review path: Brain mission execution created its Reasoning Ledger through the in-memory mission adapter while the operator review endpoint resolves ledgers through the SQL-backed operational service. The returned ledger ID could therefore be absent from durable storage and fail review with `LEDGER_NOT_FOUND`.

The operator now performs a fail-closed synchronization before exposing the mission result:

- retrieves the exact immutable source ledger from the Brain mission adapter;
- creates the corresponding deterministic operational ledger only when absent;
- requires ledger identity, tenant/project scope, title, and description to match;
- requires any already-durable entries to be a fingerprint-identical prefix of the source snapshot;
- appends only missing entries with optimistic expected-version checks;
- requires the final durable ledger version to exactly match the mission snapshot;
- treats any divergence as `MISSION_LEDGER_DIVERGED` or another explicit validation error rather than translating, replacing, or duplicating reasoning records.

Focused regression coverage proves first-write synchronization, idempotent replay, exact fingerprint preservation, and fail-closed divergence handling.

## Governance

- `automatic_publication` is always false.
- human review remains mandatory.
- reviewer identity cannot be supplied by the request body.
- cross-tenant mission lookup returns `MISSION_NOT_FOUND`.
- publication requests with `explicit_owner_confirmation=false` fail before construction of the publication service or graph gate.
- tests do not invoke the production graph publication service.
- no private chain-of-thought is stored or exposed.
- no deployment or taxonomy activation authority is introduced by this operator facade.

## Executable validation

P1 repair implementation head `38b4e0c8af10505cc63cb5748496c3e4742f7a83` passed all triggered executable gates:

- `CALYX-CORE-REBASE-004 Validation` run `31218640891`: success — compile, focused operator tests, reasoning-publication regression, Ruff, and diff hygiene;
- `CALYX Eligible Ledger Discovery` run `31218640809`: success;
- `CALYX-CORE-REBASE-002A Validation` run `31218641046`: success;
- `BUILD-088E Validation` run `31218640830`: success;
- `CALYX Brain End-to-End Certification` run `31218640802`: success — joined literature-to-publication acceptance, controlled publication lifecycle regressions, and PostgreSQL migration certification;
- `CALYX-BRAIN-003 Validation` run `31218640791`: success — PostgreSQL migration order/reapplication/constraints, publication adapter, Brain/Knowledge Graph regressions, Candidate Knowledge/Literature/Research Station regressions, Ruff, route smoke, and repository hygiene.

This Brain-only update records the completed repair and validation evidence; it does not change runtime behavior.
