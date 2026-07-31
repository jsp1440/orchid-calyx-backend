# BUILD-105 — Harvester Safety Hardening

## Purpose

Harden the already-merged BUILD-093 iNaturalist, GBIF, and EOL/TraitBank harvesters without replacing their mature source-specific implementations or bypassing the BUILD-049 governed control plane.

## Why this build exists

The recovered Replit audit identified failure patterns that can produce runaway, zero-yield work:

- GBIF offset paging at or beyond the 100,000-record search window
- cursors resetting to zero or moving backwards
- repeated pages and duplicate storms
- sustained empty pages without a circuit breaker
- executions without explicit runtime, request, record, or write budgets
- malformed records lacking an operational dead-letter destination

BUILD-093 already migrated working harvesters into Calyx. BUILD-105 therefore adds reusable controls rather than introducing a second harvesting engine.

## Changes

### `harvesters/safety.py`

Adds dependency-light controls:

- `WorkBudget` — caps runtime, requests, records, and database writes
- `CircuitBreaker` — opens after sustained empty pages or total attempted-record failure
- `CursorGuard` — rejects reset-to-zero and backward cursor movement
- `RepeatedPageDetector` — identifies identical result pages using deterministic fingerprints
- `enforce_gbif_offset` — rejects offset windows beyond 100,000

### `migrations/BUILD-105-harvester-safety.sql`

Additive, generated-only migration for:

- `oc_admin.harvest_safety_state`
- `oc_admin.harvest_dead_letter`
- unresolved dead-letter lookup indexes

The migration is not executed by this branch. It deliberately avoids adding target-table uniqueness constraints until the deployed canonical media tables are inventoried for legacy duplicates.

### Tests

`tests/test_build_105_harvester_safety.py` covers:

- every work-budget dimension
- empty-page and total-failure circuit opening
- cursor regression prevention
- repeated-page detection
- GBIF offset-ceiling enforcement

## Integration status

This build is the safety foundation. It does **not yet alter** `harvesters/execution.py` or the mature source modules. That wiring should be performed source by source after confirming each harvester's native pagination and persistence contracts:

1. GBIF: inspect checkpoint before request and enforce the 100k window or partition query.
2. iNaturalist: prevent cursor reset and reject repeated pages.
3. TraitBank: cap processed records and writes per invocation.
4. All sources: persist safety snapshots and dead letters after migration approval.
5. Add explicit `dry_run` / `audit_only` invocation mode through the governed worker path.

## Deployment and safety

- No production database changes were executed.
- No harvester was run.
- No external source API was called.
- No automatic scheduling was enabled.
- No merge or auto-merge was performed.

## Recommendation

Review and merge this safety foundation before wiring it into live source execution. Then complete the wiring as a separate bounded build with offline mocks and a production-like dry run before enabling any scheduled writes.
