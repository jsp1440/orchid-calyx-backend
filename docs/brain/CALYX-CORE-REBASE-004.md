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

- `POST /missions` starts the existing bounded Brain evidence mission with tenant and actor derived from authentication.
- `GET /missions/{mission_id}` exposes a safe operator summary and hides cross-tenant mission existence.
- `GET /ledgers/eligible` uses the same current-version, owner-scoped eligibility query as the existing reasoning-publication API.
- `POST /ledgers/{ledger_id}/review` records a durable Reasoning Ledger review with reviewer identity derived from authentication.
- `POST /publications` requires `explicit_owner_confirmation=true`, an expected ledger version, and the exact current review-content hash before invoking the existing governed publication service.
- `GET /publications/{ledger_id}` returns owner-scoped publication history.
- `GET /graph/version` deliberately does not invent a graph version; it reports `graph_version: null` and current operational blockers.
- `GET /panel` combines optional mission state, eligible ledgers, and Calyx Core readiness without performing publication or graph mutation.

## Eligibility refactor

Eligible-ledger discovery was factored out of `app.reasoning_publication.routes` into `app.reasoning_publication.eligibility`. Both the existing API and the new Mission Control facade now use one implementation, preserving current-version review-hash binding and owner isolation.

## Governance

- `automatic_publication` is always false.
- human review remains mandatory.
- reviewer identity cannot be supplied by the request body.
- cross-tenant mission lookup returns `MISSION_NOT_FOUND`.
- publication requests with `explicit_owner_confirmation=false` fail before construction of the publication service or graph gate.
- tests do not invoke the production graph publication service.
- no private chain-of-thought is stored or exposed.
- no deployment or taxonomy activation authority is introduced.

## Validation gate

Before merge, the unchanged head must pass:

1. `CALYX-CORE-REBASE-004 Validation`, including focused operator tests, reasoning-publication regression, Ruff, compile, and diff hygiene.
2. `BUILD-088E Validation` because the facade touches the controlled publication path and shared Calyx Core routing.
3. Relevant Brain/end-to-end regression workflows that GitHub triggers for the changed paths.

Any substantive review finding must be fixed and the resulting exact head revalidated before merge.
