# CALYX Production Certification V3

Date: 2026-08-07
Issue: #469
Base main: `e5d3a20299768f5b0e5839da4aae8af36a015ff0`
PR: #590

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

## Demonstrated failures corrected

The first PR validation attempt stopped at Ruff because the two local imports inside the live probe were not in Ruff's canonical order. No behavior tests ran. Import order was corrected without changing the contract.

The second attempt passed compile/Ruff but failed during test collection because the new workflow omitted `PYTHONPATH=.` and `httpx`, which are required by the repository's existing certification regression suites. The validation harness was corrected; application logic was unchanged by that repair.

## Validation evidence

Implementation head `87a0b0806d38eb431298ba0fe2bc5bd91fa3bb77` passed the complete release matrix:

- CALYX Production Certification V3 — run `31227802526`: **success**;
- CALYX-CORE-REBASE-002A Validation — run `31227802469`: **success**;
- CALYX Workflow Governance Audit — run `31227802512`: **success**;
- BUILD-088E Validation — run `31227802517`: **success**.

The dedicated certification run passed compilation, Ruff, new production-observability tests, both existing Calyx Core certification regression suites, read-only governance smoke, Brain smoke, and diff hygiene.

The final Brain/documentation head must re-pass the triggered release gates before merge; implementation-head results are not reused as final-head evidence.

## Remaining deployment configuration dependencies

The implementation intentionally does not invent live state. A deployed certification may report explicit blockers until the deployment environment supplies or exposes:

- `CALYX_EXPECTED_MAIN_COMMIT` for authoritative deployed-vs-main comparison;
- `CALYX_GRAPH_VERSION` or an equivalent read-only graph version probe;
- the operational engineering queue table in the bound production database, if queue metrics are expected there;
- Reasoning Ledger/publication relations if production migrations 103/105 have not been activated.

These are reported with exact remediation and do not trigger mutation automatically.

## Release boundary

Merging #590 changes only the protected read-only certification surface. It does not deploy the code to production and does not execute the owner-governed Reasoning Schema Production Activation workflow.

Exact final-head run identifiers will be recorded before release.
