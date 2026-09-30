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
- `orchid_api.py` was a standalone FastAPI app. Its `GET /api/occurrences` returned raw database latitude/longitude with no authentication and wildcard CORS. `app.main` did not mount it, and nothing imported it or launched it from `.replit`, a Procfile or a workflow. A legacy safety lock made it exit on import unless `OC_ALLOW_LEGACY_OC_SCRIPT_RUN` was set to its acknowledgement value, so it was not reachable by accident. Anyone who set that variable and ran `uvicorn orchid_api:app` got the unauthenticated endpoint, so the lock was a speed bump, not an access control. The authenticated exact-coordinate path, `api_occurrence_points.py` behind `verify_owner_or_api_key`, is unchanged.

Removing the files at the tip is required by the repository's own policy:

- Brain KO-0043: the public Atlas generalises rare, threatened and collection-sensitive taxa.
- Frontend `src/features/atlas-next/sensitivity.ts`: unresolved taxa fail closed to a 0.05 degree cell, and CR/EN/VU records are generalised.
- `corpus/design_intelligence/build-089c/research/calyx_dim10.md`: CITES Appendix I taxa are generalised to at least 0.1 degree.

A committed data file bypasses every one of those runtime safeguards.

## Guard against recurrence

- `scripts/check_no_precise_coordinates.py` fails on any tracked file that carries latitude/longitude-like values finer than 2 decimal places. It reports paths and counts, never values. It reads:
  - CSV/TSV files, which are streamed. The delimiter is sniffed, UTF-8 BOMs are handled, the header row can be anywhere, comma decimals and exponent notation are parsed, and WKT in cells is found. Header names include Spanish `Latitud`/`Longitud` and the abbreviations `lat.`/`long.`.
  - XLSX workbooks, with the same header search.
  - JSON, GeoJSON (every geometry type), JSON Lines and YAML, including:
    - coordinate-named keys holding a list or dict of values (`{"lat": [...]}`, pandas `orient="columns"`);
    - pandas `orient="split"` tables;
    - position lists under keys such as `points` or `path`.
  - Anonymous numeric pair arrays (a top-level `[[lon, lat], ...]` or pandas `orient="values"`). These count only when at least 5 rows, and at least 80% of rows, hold an in-range pair finer than 2 dp in the same two adjacent columns. One or two such pairs are common in ordinary numeric data; five aligned rows is the shape of a point list. A shorter anonymous list is not flagged. One under a coordinate or position key always is.
  - Notebooks: every cell source and every output (`text/plain`, `text/html`, stream text, JSON) goes through the same table, header, JSON and pattern detectors as files. That includes DataFrame reprs and HTML tables, printed CSV, Python literals such as `pd.DataFrame({"lat": [...]})`, and `folium.Marker([lat, lon])`.
  - SQL `INSERT`/`COPY` dumps, KML/KMZ, GPX and HTML: Leaflet markers, `L.latLng`/`new L.LatLng`, polylines and polygons, embedded GeoJSON, folium `location=`, and tables.
  - Members of zip, gzip and tar archives.

  Anything it cannot verify fails closed. That covers an unreadable, corrupt (including a bad deflate stream in a gzip, zip or tar member) or oversized file, a Parquet file it cannot read, and a tracked path missing from the working tree (a sparse checkout).

  The 2 dp threshold is a floor for tracked files. It is not a statement of compliance with the per-taxon rules above: sensitive taxa need coarser generalisation, and occurrence data should not be committed at all.

  The only exemption is an explicit allowlist of small synthetic fixtures under `tests/`. That allowlist is currently empty.

  Documented follow-ups, not implemented:
  - scanning source code (`.py`, `.js`, `.ts`) and Markdown;
  - UTF-16 text;
  - degree-minute-second notation;
  - `x`/`y` pairs outside a geometry or CRS context;
  - mysqldump `INSERT` statements without a column list;
  - further suffixes (for example `.geopkg`, `.shp`, `.dbf`, `.ods`).
- `tests/test_no_precise_coordinates.py` runs the guard over `git ls-files`. The guard runs in CI only when a workflow runs that test, and Orchid Autonomous Backend Validation runs only the test files a pull request changes. `.github/workflows/oc-critical-suites.yml` runs on every pull request and push to `main` and `oc-autonomous-integration`. This change lists this test and `tests/test_legacy_occurrence_api_fail_closed.py` in that workflow's required `OC_CRITICAL_PRIVACY_SUITES`.
- `tests/test_legacy_occurrence_api_fail_closed.py` parses every standalone FastAPI route handler outside `app/`. It fails when a handler that touches coordinate names does not actually depend on `verify_owner_or_api_key`, whether through the decorator, a parameter dependency, the app's dependencies, or a wrapper that calls the check.
- `.gitignore` now lists the generated exact-coordinate outputs.

## Test canaries replaced

The redaction tests use planted coordinate literals to prove that locality is stripped. Several of those literals were real-looking pairs: some were labelled with named real sites next to real taxa and provinces, and some sat within a few kilometres of removed occurrence records.

Each of those real-looking literals in tracked files has been replaced with a synthetic open-ocean value of the same sign, digit shape and precision. That covers decimal pairs, degree-minute pairs, hemisphere-prefixed forms such as `N..`/`W..`, and one value that reappeared as a "measurement". The two-decimal half of a pair was replaced along with it. Each replacement is consistent everywhere the literal appears, including the "must not leak" assertions. The redaction tests still exercise the same paths: with each module's locality redaction disabled in a scratch copy, the affected test files fail.

`tests/test_no_precise_coordinates.py::test_retired_real_looking_canaries_do_not_return` holds truncated SHA-256 digests of the 36 retired literals, never the values. It fails if any of them appears in a tracked file again. The pre-change files still hold them, and the test finds 23 in the old `tests/test_member_read_access.py` alone. The values remain in git history, as everything else here does. Parametrized test IDs in the affected files use neutral labels, so no literal appears in CI logs.

## What this change does not do

The removed content remains in git history, on `main`, and on essentially every
remote branch: 1,942 remote heads were counted on 2026-09-30. Anyone can still
read it from the public repository. This change does not rewrite history, because
that is destructive and owner-gated.

## Owner actions required

1. **History and visibility decision.** Either rewrite history to purge these paths (for example with `git filter-repo`, followed by a coordinated force-push of every branch and invalidation of existing clones), or make the repository private. Either way, also remove the paths from `main` through the normal owner-governed promotion path. Know the limits of each option:
   - A rewrite does not reach the pull-request refs. The repository has about 1,400 `refs/pull/*` refs (1,397 counted on 2026-09-30), which the owner cannot delete or force-push. They keep the old commits reachable.
   - GitHub's cached views of those commits and diffs need a removal request to GitHub Support.
   - Making the repository private does not remove existing public forks, which keep their copies.
2. **Provider notification.** Tell the data providers whose records were exposed (iNaturalist, Tropicos and the herbarium sources named in the `source` property). Put the *Phragmipedium* (CITES Appendix I) records first.
3. **Exposure assessment.** Review forks, clone and traffic statistics, and any mirrors or caches of the public repository for the period since the files were first committed, to judge how widely the coordinates may have been copied.
4. The agent asset metadata (`.agents/agent_assets_metadata.toml`) still lists `ecuador_orchids.geojson.json` as an output. `.agents/**` is an owner-checkpoint path, so this change leaves that entry alone. The entry holds no coordinates.
