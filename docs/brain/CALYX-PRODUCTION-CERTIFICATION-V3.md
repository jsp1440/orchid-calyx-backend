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

## Deployed production evidence — 2026-08-08 UTC

Issue #469's remaining deployed-evidence criterion was completed with a temporary read-only GitHub-hosted probe and the temporary PR was closed unmerged.

Successful evidence run `31241617490`, job `93063471965`, verified:

- `/health`: HTTP 200;
- protected owner session: HTTP 200;
- `/api/mission-control/calyx-core/certification`: HTTP 200;
- deployed Render commit `c114aba0545a71a3be23375e5b6d84e624fa82b4`;
- repository `main` at capture `c114aba0545a71a3be23375e5b6d84e624fa82b4` — exact match;
- evidence receipt hash `1d8c8e04fb14f4f0ac9848c2a1219ff378bf1e8a6a43d5d9c5e94b60c4da6ccb`;
- GitHub artifact ID `9017198288`;
- artifact ZIP SHA-256 `99e8bd21ac00a5a35720cb056643ca9bd93291432506ea1e0b6504bfeb3169eb`.

The receipt explicitly records read-only execution and no migration, publication, taxonomy activation, production database mutation, or Knowledge Graph mutation.

The deployed report exposed four production blockers without attempting remediation automatically:

- `REASONING_SCHEMA_INCOMPLETE` — the four Reasoning Ledger/publication relations are absent; activation remains owner-governed in issue #580;
- `EXPECTED_MAIN_COMMIT_UNAVAILABLE` — the release environment does not expose `CALYX_EXPECTED_MAIN_COMMIT`, although the independently captured deployed SHA matched `main` exactly;
- `GRAPH_VERSION_UNAVAILABLE` — no explicit deployed graph-version identifier is exposed;
- `ENGINEERING_QUEUE_METRICS_UNAVAILABLE` — the optional operational queue metrics relation/probe is unavailable.

Issue #469 was then closed as completed because the deployed certification surface had been exercised successfully and its purpose is to report production readiness truthfully, not to auto-clear its blockers.

## Optional PostgreSQL probe isolation follow-up

The same live evidence revealed a robustness defect: PostgreSQL connectivity had succeeded (`reachable=true`) but the report also contained `database.error_type=InternalError`. The optional engineering-queue group-count query had encountered an unavailable relation; PostgreSQL marked the transaction aborted, and the subsequent optional scalar query leaked that aborted transaction into the top-level database-health result.

Follow-up PR #609 corrects the boundary:

1. optional relations are checked with `to_regclass` before querying them;
2. optional group-count and scalar probes execute inside nested transactions/SAVEPOINTs;
3. an optional metric failure returns unavailable state without poisoning the enclosing read-only connection;
4. the top-level database error is reserved for connection or base-probe failure;
5. PostgreSQL 16 regression coverage reproduces the missing-queue-table condition and requires `reachable=true`, `dialect=postgresql`, and `error_type=None` while retaining `ENGINEERING_QUEUE_METRICS_UNAVAILABLE`.

This correction changes observability only. It creates no queue table and performs no production mutation.

## Remaining deployment configuration dependencies

The implementation intentionally does not invent live state. A deployed certification may report explicit blockers until the deployment environment supplies or exposes:

- `CALYX_EXPECTED_MAIN_COMMIT` for authoritative deployed-vs-main comparison;
- `CALYX_GRAPH_VERSION` or an equivalent read-only graph version probe;
- the operational engineering queue table in the bound production database, if queue metrics are expected there;
- Reasoning Ledger/publication relations if production migrations 103/105 have not been activated.

These are reported with exact remediation and do not trigger mutation automatically.

## Release boundary

The certification surface and its probe-isolation correction are read-only. They do not execute the owner-governed Reasoning Schema Production Activation workflow, publish reviewed science, activate taxonomy, deploy code, or mutate the production Knowledge Graph.
