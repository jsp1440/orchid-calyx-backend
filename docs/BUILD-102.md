# BUILD-102 — iNaturalist Harvester V2 Plugin

## Scope

BUILD-102 adds an iNaturalist observation and media source plugin to the BUILD-101 Harvester V2 framework. It does not redesign the framework, download media binaries, perform literature extraction, or publish records directly into the Orchid Continuum knowledge graph.

## Source interface

The plugin uses the official iNaturalist v1 observations API at `/v1/observations`. Requests are ordered deterministically by observation identifier and support page-based continuation.

## Configuration and checkpointing

Checkpoint state includes page, page size, taxon identifier or name, quality grade, photo filter, captive/cultivated filter, and processed-record count. The default taxon query is `Orchidaceae`. Page size is constrained to 1–200 records.

## Normalization

Each observation is normalized into the canonical BUILD-101 occurrence shape with source identifier, scientific name, taxon identifier, coordinates when public, locality, event date, observer, observation license, quality grade, captive status, positional accuracy, source URL, and the raw source payload.

Photographs remain distinct source records. The plugin preserves photo identifier, original and derivative URLs, attribution, photo license, publisher, MIME type, and source photo URL. Observation licenses and photo licenses are not treated as interchangeable.

## Validation

A normalized occurrence requires an iNaturalist observation identifier and a usable scientific-name assertion. Missing or obscured coordinates remain missing; the plugin never manufactures coordinates. Records can be filtered by quality grade, photo presence, and captive/cultivated status.

## Reliability

The client provides request timeouts, a project User-Agent, optional minimum request spacing, and bounded exponential retry with jitter for transport errors, HTTP 429, and server errors.

## Testing

Tests use mocked HTTP responses only and cover request construction, paging and completion, checkpoint state, normalization, coordinate parsing, required-field rejection, photo extraction and licensing, attribution, and transient retry behavior. CI also runs existing BUILD-101 manager and GBIF plugin tests to protect framework compatibility.

## Known limitations

The plugin currently uses page-based API continuation rather than export-based bulk synchronization. It preserves obscured data exactly as returned. Taxonomic names are source assertions and are not automatically resolved or published as accepted World Plants taxonomy. Media binaries are not downloaded.
