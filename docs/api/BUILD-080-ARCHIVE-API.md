# BUILD-080 Archive API

Base path: `/archive`

## POST `/archive/import`

Authentication: owner session or `X-API-Key`.

```json
{
  "source_path": "/approved/archive/root",
  "checkpoint_interval": 100,
  "extract_zip": true
}
```

Returns HTTP 202 when accepted.

## POST `/archive/resume`

Authentication: owner session or `X-API-Key`.

```json
{"run_id": "00000000-0000-0000-0000-000000000000"}
```

Returns HTTP 202 or 404 when the run does not exist.

## GET `/archive/status`

Optional query parameter: `run_id`. Without it, returns the latest run. The response includes Mission Control counters, timestamps, errors and checkpoint state.

## GET `/archive/statistics`

Returns total documents, files, entities, relationships and import runs.

## GET `/archive/documents`

Query parameters: `limit` (1–1000), `offset` (0+). Returns the document registry newest first.

## GET `/archive/entities`

Query parameters: `limit` (1–1000), `offset` (0+). Returns archive-local extracted entities newest first.
