# ACS-001 validation evidence

Maker: ChatGPT / Codex, 2026-10-13. No independent checker acceptance is claimed.

## Executed locally
- Test-first store and transport cases initially failed for missing implementation. Later replay regressions demonstrably failed for edited-comment assignment injection and previously refused claims executing after timeout. Both were fixed with an atomic durable inbox ledger.
- `python -m pytest -q tests/coordination`: 26 passed, 4 skipped. Skips are precisely the four local PostgreSQL integration tests, not safety/auth tests.
- `python -B -m unittest discover -s tests/coordination -v`: equivalent SQLite, signed HTTP and fake-GitHub coverage. A real loopback HTTP server exercised signed assignment, claim, heartbeat, response, wakeup, webhook scope and replay.
- SQLite restart/dedup, simultaneous claims via two separate connections, stale-token/attempt fencing, timeout retries/dead letter, hard deadline, exact owner digest/expiry, unknown/stale health, outbox recovery and uncertain POST reconciliation are covered.
- Lint uses repository-pinned ruff 0.16.8. Broad exception handlers are intentionally limited to service error-sanitization boundaries; they report fixed errors without leaking secrets.
- Compilation and diff whitespace checks are included in final verification. Security guard is run on the committed change.

## Repository-wide comparison
`python -m pytest -q` was executed on the change and on detached unchanged main at 6444eb696f46ed57daf5c45b6abed8c19e3ee471 in the same environment. Both stopped during collection with the same 349 error-node IDs, due to unavailable fastapi/httpx/psycopg2/requests/sqlalchemy/starlette dependencies. The file REPOSITORY-COLLECTION-ERRORS.txt records all error nodes. This establishes matching collection failures only; it does not establish a passing repository suite or absence of runtime regressions.

An earlier branch collection run had an extra import-name collision with tests/kernel/test_runtime.py. Renaming the new test modules to test_acs_* removed it; the subsequent compared error sets are identical.

## Explicitly unverified
- PostgreSQL backend execution: no local server was available. System package installation failed under process/identity restrictions; a user-space bundled server also could not initialize its required OS identity. No permission escalation occurred. Four guarded tests are prepared for the workflow's disposable PostgreSQL 16 service, and reject any remote/production test URL.
- Hosted CI: pending until actual workflow/job evidence on the published head is inspected. Skipped/no-runner/zero-step results are never passing evidence.
- Live GitHub bridge delivery with production credentials; live webhook registration; real ChatGPT/Claude/Kimi/Copilot/Calyx adapters.
- Hosted persistence, cost/capacity and TLS/proxy acceptance.

## Owner boundary
No merge, Render activation, Neon SQL/migration, production database change, provider call or paid infrastructure creation occurred. GitHub progress comments and draft code publication are authorized. Running the service persistently requires an approved host/schema and distinct agent identities; current consumer-chat sessions cannot be assumed to be callable background agents.
