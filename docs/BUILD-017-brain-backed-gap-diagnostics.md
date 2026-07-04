# BUILD-017 — Brain-backed Gap Diagnostics

BUILD-017 upgrades BUILD-016 knowledge-gap discovery by adding Brain database evidence.

## Purpose

BUILD-016 can tell Calyx that a runtime domain is missing or thin. BUILD-017 checks whether that domain already exists in the Orchid Continuum Brain as schemas or tables. This separates two very different situations:

1. The data is genuinely missing.
2. The data exists, but the runtime has not been wired to it yet.

## Added

- `runtime/knowledge_gap_diagnostics.py`
- Brain-aware diagnostics that inspect `information_schema` when `DATABASE_URL` is available
- Safe degraded mode when `DATABASE_URL` or `psycopg` is unavailable
- File-backed diagnostic cache under `runtime/knowledge_gap_diagnostics/latest.json`
- Runtime endpoints for diagnostics, gaps, domains, queue, and dashboard
- Tests with a supplied fake Brain inventory

## API endpoints

- `POST /api/runner/knowledge-diagnostics/discover`
- `GET /api/runner/knowledge-diagnostics/latest`
- `GET /api/runner/knowledge-diagnostics/domains`
- `GET /api/runner/knowledge-diagnostics/gaps`
- `GET /api/runner/knowledge-diagnostics/queue`
- `GET /api/runner/knowledge-diagnostics/dashboard`

## Behavior

The diagnostic engine reads the latest BUILD-016 report, fetches or accepts a Brain schema/table inventory, scores each Orchid Continuum domain using both runtime coverage and Brain table evidence, then produces an adjusted gap list.

If Brain evidence exists for a domain, BUILD-017 recommends promoting those existing Brain tables into runtime validators and review-ready outputs rather than treating the domain as empty.

## Acceptance check after deploy

1. Run `POST /api/runner/knowledge-diagnostics/discover`.
2. Run `GET /api/runner/knowledge-diagnostics/dashboard`.
3. Run `GET /api/runner/knowledge-diagnostics/domains`.
4. Confirm responses report `BUILD-017`.
5. Confirm the response includes a `brain` section with connection status.

## Next build

BUILD-018 should begin table-level adapter planning: choose specific Brain tables per domain, recommend adapter names, identify required columns, and generate runtime wiring tasks.
