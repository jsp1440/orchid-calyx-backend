# BUILD-103 — BHL Harvester V2 Plugin

## Objective

Implement a production-quality Biodiversity Heritage Library API v2 plugin on the BUILD-101 harvesting framework without redesigning the framework.

## Implementation

The plugin is located at `app/harvest/plugins/bhl/` and registers `BHLHarvester` with the existing harvester registry.

### API operations

- `ItemSearch`
- `PartSearch`
- `PageSearch`
- `GetItemMetadata`
- `GetPartMetadata`
- `GetPageOcrText`
- `GetPageImages`
- `GetItemPDFs`

### Canonical output

Normalized records preserve:

- BHL source identifier
- object type (`item`, `part`, or `page`)
- title
- authors
- publication
- year
- volume and issue
- page numbers
- DOI
- stable URL
- OCR text
- plate and PDF media
- rights and license
- retrieval timestamp
- original raw source payload

### Checkpoints

`fetch_page()` accepts and returns checkpoint state containing:

- `page`
- `entity`
- `search_term`
- `processed`

This makes item, part, and page searches restartable through the existing BUILD-101 checkpoint manager.

### Reliability

`BHLClient` provides:

- configurable request timeout
- exponential backoff with jitter
- retry handling
- request rate limiting
- structured BHL API error validation
- deterministic request parameters

`BHL_API_KEY` is required at runtime and may be supplied through the environment.

## Validation

Run:

```bash
python -m pytest -v tests/harvest/test_bhl_plugin.py
python -m pytest -v tests/harvest
```

Tests use mocked HTTP and do not require the live BHL service.

## Acceptance criteria

- BUILD-101 framework reused unchanged
- BHL plugin registered
- item, part, and page pagination implemented
- checkpoint resume state preserved
- bibliographic provenance preserved
- OCR preserved
- botanical plate and PDF media preserved
- rate limiting and retry behavior tested
- no NLP or semantic extraction introduced
