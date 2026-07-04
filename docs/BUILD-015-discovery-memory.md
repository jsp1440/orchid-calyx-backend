# BUILD-015 — Discovery Memory

BUILD-015 persists BUILD-014 autonomous discovery snapshots so Calyx can remember what it discovered, compare snapshots over time, and detect changes in modules, capabilities, recommendations, and dependency graph shape.

## Added

- `runtime/discovery_memory.py`
- Discovery snapshot endpoints on the existing `/api/runner` router
- Discovery snapshot tests

## API endpoints

- `POST /api/runner/discovery-snapshots/capture`
- `GET /api/runner/discovery-snapshots/latest`
- `GET /api/runner/discovery-snapshots`
- `GET /api/runner/discovery-snapshots/diff`
- `GET /api/runner/discovery-snapshots/timeline`
- `GET /api/runner/discovery-snapshots/health`

## Behavior

The discovery memory store runs BUILD-014 discovery, writes timestamped JSON snapshots under `runtime/discovery_memory/`, maintains a `latest.json` pointer, summarizes snapshot history, compares the two most recent snapshots, and exposes health/timeline endpoints.

## Acceptance check after deploy

1. Run `POST /api/runner/discovery-snapshots/capture`.
2. Run `GET /api/runner/discovery-snapshots/latest`.
3. Run `GET /api/runner/discovery-snapshots`.
4. Run `GET /api/runner/discovery-snapshots/diff`.
5. Run `GET /api/runner/discovery-snapshots/health`.
6. Confirm responses report `BUILD-015` and at least one snapshot exists.

## Next build

BUILD-016 should move from remembering software discovery to knowledge-gap discovery across Orchid Continuum scientific data.
