# BUILD-017 — Brain-backed Gap Diagnostics

BUILD-017 upgrades BUILD-016 from runtime-only knowledge-gap detection into live Brain-aware diagnostics.

## Purpose

BUILD-016 correctly identifies which Orchid Continuum research domains are not yet connected to the runtime. BUILD-017 begins connecting those gap signals to live Brain table inventory and estimated row counts so Calyx can distinguish between:

- data that does not exist yet,
- data that exists in the Brain but is not wired into runtime services,
- data that is wired but still needs field-level completeness checks.

## Added

- `runtime/brain_gap_diagnostics.py`
- Optional live database inspection through `DATABASE_URL`
- Domain-to-table matching for Taxonomy, Images, Occurrences, Pollination, Mycorrhiza, Conservation, Literature, Traits, and Governance
- Enriched gap records that include candidate Brain tables, estimated rows, and recommended next steps
- Degraded fallback behavior when database access is unavailable
- Tests for degraded mode and table matching logic

## Planned endpoints

The diagnostics service is ready for router exposure as:

- `GET /api/runner/brain-gap-diagnostics/status`
- `GET /api/runner/brain-gap-diagnostics`
- `GET /api/runner/brain-gap-diagnostics/domains`
- `GET /api/runner/brain-gap-diagnostics/gaps`
- `GET /api/runner/brain-gap-diagnostics/queue`
- `GET /api/runner/brain-gap-diagnostics/dashboard`

## Acceptance check after router exposure

1. Run `GET /api/runner/brain-gap-diagnostics/status`.
2. Run `GET /api/runner/brain-gap-diagnostics/dashboard`.
3. Confirm responses report `BUILD-017`.
4. Confirm that live deployments with `DATABASE_URL` report table counts and domain matches.
5. Confirm deployments without `DATABASE_URL` return degraded fallback rather than crashing.

## Next build

BUILD-018 should persist enriched gap diagnostics into approved Brain tables and create stable identifiers for gap observations, evidence records, and implementation tasks.
