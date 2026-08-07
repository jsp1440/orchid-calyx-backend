# CALYX Eligible-Ledger Discovery Observability

Date: 2026-08-07
Base main: `0cebe8f84b58cf0129954991bfe9785ac0eafb18`
Repair PR: #584
Source diagnostic: temporary PR #578
Implementation head: `329bdc9f67105282bd19a97c455682b01ba23c4a`

## Demonstrated failure

Temporary read-only publication-eligible ledger discovery run `31225544733` validated the protected deployment URL and owner access secret, then failed while calling `/api/reasoning-ledgers/eligible-for-publication` because the deployed backend returned HTTP 503 Service Unavailable.

The diagnostic exposed a second local defect: `scripts/discover_eligible_reasoning_ledgers.py` raised the HTTP exception before writing `calyx-eligible-ledger-discovery.json`. The always-run artifact upload therefore also failed because no receipt existed.

No publication endpoint was invoked, no ledger was reviewed or approved, and no Knowledge Graph or production data mutation occurred.

## Repair

The read-only discovery utility now:

- retries transient HTTP 502/503/504 responses a maximum of three attempts with bounded backoff;
- retries bounded network failures;
- converts terminal HTTP, network, configuration, owner-session, response-shape, and unexpected discovery-status failures into typed `DiscoveryFailure` records;
- always supports a structured failure receipt containing failure stage/code, HTTP status where available, attempt count, and explicit read-only/non-mutation flags;
- redacts owner access codes, bearer/session tokens, and low-level network error detail from persisted evidence;
- hashes both success and failure receipts using canonical JSON;
- exits nonzero on discovery failure while still writing the evidence file;
- preserves the distinction between a successful discovery with zero eligible ledgers and an unavailable backend.

## Compatibility preservation and repair sequence

The first repair head compiled successfully but Ruff exposed two focused style defects (`UP035` and `PYI034`); both were corrected before expanding scope.

The existing `CALYX Eligible Ledger Discovery` regression then exposed a compatibility issue in the refactor: established operator tests monkeypatch module-level `ACCESS_CODE` and the historical two-value `call()` seam. The repair deliberately preserves:

- module-level `BASE_URL` and `ACCESS_CODE` configuration seams;
- `call(path, method="GET", payload=None, token="") -> (status, body)` for existing operators/tests;
- optional dependency injection for focused retry testing without changing the legacy call shape.

A subsequent contents-API branch-write race temporarily combined the updated two-value test with the earlier three-value script implementation. Rather than layering further writes onto an inconsistent history, #584 was rebuilt atomically as one commit directly on then-current main `0cebe8f84b58cf0129954991bfe9785ac0eafb18`. That atomic rebuild is the authoritative implementation candidate.

Retries remain internal to `call()`, while terminal failures carry their attempt count in `DiscoveryFailure` and the persisted failure receipt.

## Executable validation evidence

Atomic implementation head `329bdc9f67105282bd19a97c455682b01ba23c4a` passed all triggered release gates:

- Eligible Ledger Discovery Observability `31226292116` — success;
- CALYX Workflow Governance Audit `31226292233` — success;
- BUILD-088E Validation `31226292150` — success;
- CALYX Eligible Ledger Discovery `31226292154` — success for operator validation/regression.

The focused observability workflow passed Python 3.13 compile, Ruff, all focused retry/failure-receipt/redaction tests, read-only contract smoke, Brain smoke, and diff hygiene.

The repository-standard CALYX Eligible Ledger Discovery PR workflow passed its operator validation and existing `tests/test_eligible_ledger_discovery.py` regression. Its live protected-backend discovery and artifact-upload steps were correctly skipped because that workflow intentionally executes those steps only for non-pull-request events. Therefore this PR evidence does **not** establish that the earlier backend HTTP 503 has cleared, that a live eligible ledger exists, or that no eligible ledger exists.

## Governance

This utility remains read-only. It requests an owner session and queries the eligible-ledger discovery endpoint only. It does not invoke publication, review, approval, taxonomy activation, deployment, production database mutation, or production Knowledge Graph mutation.

A backend HTTP 503 is not evidence that no eligible ledger exists. It is recorded as backend-unavailable evidence and must not be converted into a publication target or eligibility conclusion.

## Release requirement

The final documentation head must rerun the focused observability gate and relevant governance/publication regressions before merge. The next actual live backend discovery must occur through the existing non-PR workflow path after this repair is on main; its result must be treated as evidence only, not as authority to publish.
