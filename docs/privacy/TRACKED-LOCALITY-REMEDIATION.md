# Tracked occurrence-locality remediation

Status: files removed from the tip of `oc-autonomous-integration` by this change.
The data is still in git history, which only the owner can change.

This document contains no coordinate values. Keep it that way.

## What was removed and why

This repository is public. The files below were tracked, and each one carried raw
occurrence coordinates. No runtime code read any of them.

| Path | Content (counts only) | Consumer |
|---|---|---|
| `orchid_points.csv` | 32,292 rows with `decimal_latitude`/`decimal_longitude` only; 9 distinct pairs; 4 to 6 decimal places | only the dead `orchid_atlas.py` |
| `ecuador_orchids.geojson` | 544 `Point` features, 532 of them finer than 2 decimal places. Properties: `scientific_name`, `accepted_name`, `genus`, `country`, `state_province`, `source` (mostly iNaturalist research-grade, plus Tropicos and others) and `event_date`. Includes 8 *Phragmipedium* records; the genus is on CITES Appendix I. | none |
| `ecuador_orchids.geojson.json` | byte-identical copy of the file above | none (named only in agent asset metadata) |
| `orchid_atlas.html` | generated folium map with 20,000 `circleMarker` points, all finer than 2 decimal places; lat/lon only | none |

Two scripts were removed along with the files:

- `orchid_atlas.py` read `orchid_points.csv` and wrote `orchid_atlas.html`. Nothing imported it, and earlier preservation audits had already classified it as dead (`docs/preservation/build_200_dependency_graph.md`).
- `orchid_api.py` was a standalone FastAPI app. Its `GET /api/occurrences` returned raw database latitude/longitude with no authentication and wildcard CORS. `app.main` did not mount it, and nothing imported it or launched it from `.replit`, a Procfile or a workflow. It was still runnable with `uvicorn orchid_api:app`. The authenticated exact-coordinate path, `api_occurrence_points.py` behind `verify_owner_or_api_key`, is unchanged.

Removing the files at the tip is required by the repository's own policy:

- Brain KO-0043: the public Atlas generalises rare, threatened and collection-sensitive taxa.
- Frontend `src/features/atlas-next/sensitivity.ts`: unresolved taxa fail closed to a 0.05 degree cell, and CR/EN/VU records are generalised.
- `corpus/design_intelligence/build-089c/research/calyx_dim10.md`: CITES Appendix I taxa are generalised to at least 0.1 degree.

A committed data file bypasses every one of those runtime safeguards.

## Guard against recurrence

- `scripts/check_no_precise_coordinates.py` scans every tracked CSV, TSV, GeoJSON, JSON, Parquet and XLSX file, plus Leaflet markers in HTML. It fails when a file has latitude/longitude-like columns or keys, or GeoJSON Point geometries, with values finer than 2 decimal places. It reports paths and counts, never values. The 2 dp threshold is a floor for tracked files, not a statement of compliance with the per-taxon rules above: sensitive taxa need coarser generalisation, and occurrence data should not be committed at all. The only exemption is an explicit allowlist of small synthetic fixtures under `tests/`, and that allowlist is currently empty.
- `tests/test_no_precise_coordinates.py` runs the guard over `git ls-files`, so any CI job that runs pytest enforces it.
- `tests/test_legacy_occurrence_api_fail_closed.py` fails if a standalone FastAPI app outside `app/` reads occurrence coordinates without `verify_owner_or_api_key`.
- `.gitignore` now lists the generated exact-coordinate outputs.

## What this change does not do

The removed content remains in git history, on `main`, and on essentially every
remote branch: 1,928 remote heads were counted on 2026-09-30. Anyone can still
read it from the public repository. This change does not rewrite history, because
that is destructive and owner-gated.

## Owner actions required

1. **History and visibility decision.** Either rewrite history to purge these paths (for example with `git filter-repo`, followed by a coordinated force-push of every branch and invalidation of existing clones), or make the repository private. Either way, also remove the paths from `main` through the normal owner-governed promotion path.
2. **Provider notification.** Tell the data providers whose records were exposed (iNaturalist, Tropicos and the herbarium sources named in the `source` property). Put the *Phragmipedium* (CITES Appendix I) records first.
3. **Exposure assessment.** Review forks, clone and traffic statistics, and any mirrors or caches of the public repository for the period since the files were first committed, to judge how widely the coordinates may have been copied.
4. The agent asset metadata (`.agents/agent_assets_metadata.toml`) still lists `ecuador_orchids.geojson.json` as an output. `.agents/**` is an owner-checkpoint path, so this change leaves that entry alone. The entry holds no coordinates.
