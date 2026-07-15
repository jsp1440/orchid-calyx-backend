# BUILD-065 — World Plants Version Management Guide

## Where releases are registered
`oc_source.source_snapshots` (source_system `world_plants`) — each row carries
`version_label`, `file_sha256`, `acquired_at_utc`, and provenance notes. The
raw/loaded data lives in `oc_source.world_plants_raw` / `world_plants_load`.

## Current state (2026-07-15)
| Status | Label | Snapshot | Acquired | Notes |
| --- | --- | --- | --- | --- |
| **canonical** | `2026-02` | `f8638e1d` | 2026-02-26 | from `server/data/orchids26-02.csv` |
| superseded | `Hassler_2026-02` | `b58df840` | 2026-02-24 | same `file_sha256` — duplicate registration |

Both rows share SHA `51f3640…`, i.e. they are the **same file registered
twice**. There is effectively **one** World Plants release (Hassler, Feb 2026),
34,602 loaded records.

## Adding a new release (future)
1. Register a new `source_snapshots` row with the new `file_sha256` and
   `acquired_at_utc`.
2. Re-run `select_canonical_release()` — the newest becomes canonical
   automatically; the prior canonical becomes `historical` (a different SHA) and
   is preserved.
3. Rebuild the canonical registry and re-run AUDIT → DRY_RUN → LIMITED_POPULATION
   before any publication.

**Never** delete superseded/historical releases; supersession is a status
change, not a deletion.
