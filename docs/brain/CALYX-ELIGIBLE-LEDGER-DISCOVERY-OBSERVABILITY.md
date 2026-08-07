# CALYX Eligible-Ledger Discovery Observability

Date: 2026-08-07
Base main: `4a580214b7b502eea5b5237ebaaf3f70b1d163ec`
Repair PR: #584
Source diagnostic: temporary PR #578

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

## Compatibility preservation

The first repair head compiled successfully but Ruff exposed two focused style defects (`UP035` and `PYI034`); both were corrected before expanding scope.

The existing `CALYX Eligible Ledger Discovery` regression then exposed a real compatibility issue in the refactor: established operator tests monkeypatch module-level `ACCESS_CODE` and the historical two-value `call()` seam. The repair now deliberately preserves:

- module-level `BASE_URL` and `ACCESS_CODE` configuration seams;
- `call(path, method="GET", payload=None, token="") -> (status, body)` for existing operators/tests;
- optional dependency injection for focused retry testing without changing the legacy call shape.

Retries remain internal to `call()`, while terminal failures carry their attempt count in `DiscoveryFailure` and the persisted failure receipt.

## Governance

This utility remains read-only. It requests an owner session and queries the eligible-ledger discovery endpoint only. It does not invoke publication, review, approval, taxonomy activation, deployment, production database mutation, or production Knowledge Graph mutation.

A backend HTTP 503 is not evidence that no eligible ledger exists. It is recorded as backend-unavailable evidence and must not be converted into a publication target or eligibility conclusion.

## Validation plan

Focused CI validates Python 3.13 compilation, Ruff, transient retry behavior, terminal HTTP/network receipts, access-code/token redaction, read-only success behavior, canonical receipt hashing, missing-configuration typing, source-level no-publication checks, the existing eligible-ledger discovery regression suite, Brain smoke, and diff hygiene.

Exact final-head run identifiers will be added before release.
