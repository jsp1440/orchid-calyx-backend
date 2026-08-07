# CALYX Production Certification V3

Date: 2026-08-07
Issue: #469
Base main: `e5d3a20299768f5b0e5839da4aae8af36a015ff0`

## Purpose

Extend the existing protected Calyx Core certification endpoint into one read-only production-observability surface without creating a second overlapping Mission Control API.

The existing certification contract remains compatible. Live probes are enabled only by the protected API route; direct/test callers retain the prior non-live behavior unless they explicitly request live probes.

## Added production observability

The nested `calyx-production-certification-v1` report now covers:

- deployed commit and expected-main commit comparison when both revision identifiers are supplied by the release environment;
- authentication/configuration **presence only** for database, API key, owner access, and owner session signing; secret values are never returned;
- bounded database connectivity (`SELECT 1`) with only database dialect and exception type surfaced;
- read-only PostgreSQL relation state for Reasoning Ledger/publication migrations 103 and 105;
- engineering program queue status counts and blocked-job count when the operational table is present;
- Reasoning Ledger revision status counts when the ledger schema exists;
- fail-closed continuous-worker policy/status via the existing autonomy policy;
- Knowledge Graph version from an explicit deployment-provided identifier when available;
- deterministic blocker codes and exact remediation actions for unknown/unavailable state;
- local taxonomy/literature evidence freshness timestamps in the existing pipeline readiness portion.

Unknown state is reported as unknown/unavailable rather than guessed. In particular, the service does not fetch GitHub at request time and therefore requires the deployment pipeline to provide `CALYX_EXPECTED_MAIN_COMMIT` for authoritative deployed-vs-main comparison.

## Governance

The certification request is protected by the existing `verify_owner_or_api_key` dependency. It is read-only and performs no migrations, job claims, review decisions, publication, graph mutation, taxonomy activation, credential rotation, deployment, or filesystem mutation.

No production mutation is authorized or performed by this issue.

The installed Reasoning Schema Production Activation workflow remains a separate owner-governed boundary. If certification reports missing reasoning relations, remediation points to the protected **preflight**; it does not trigger the apply branch.

## Validation plan

Focused CI covers:

- backward compatibility of the non-live certification builder;
- deployed/main drift reporting;
- database reachability on a disposable SQLite engine without writes;
- missing configuration and unknown graph-version blocker semantics;
- secret-value non-disclosure;
- protected-route/live-probe source contract;
- existing Calyx Core certification regression suites;
- workflow governance and BUILD-088E as surrounding release gates.

Exact final-head run identifiers will be added before release.
