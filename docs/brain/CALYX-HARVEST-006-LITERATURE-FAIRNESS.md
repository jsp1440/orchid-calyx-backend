# CALYX-HARVEST-006 — Literature Fairness and Scientific Corpus Lane

Status: implemented on `main`

## Decision

Literature acquisition is a first-class scientific lane and must not depend on occurrence, image, or trait backfills reaching an exhausted state.

The in-process Calyx harvester executes a bounded literature task before the adaptive biodiversity task on every cycle. This prevents long-running iNaturalist/GBIF/image work from starving the Brain and knowledge systems of scientific literature.

## Production cycle

1. Literature lane (guaranteed first)
   - Europe PMC discovery every cycle
   - Crossref DOI/scholarly metadata discovery every second cycle
   - maximum 5 records from each due provider per default cycle
   - periodic Biodiversity Heritage Library discovery when `BHL_API_KEY` is configured
   - stable/idempotent research indexing
   - review-bound evidence only
   - no automatic publication
   - no direct canonical knowledge-graph mutation
2. Biodiversity lane
   - iNaturalist freshness
   - global GBIF Orchidaceae occurrence stream, without an image-only filter
   - EOL/TraitBank fallback

Failure in either lane does not prevent the other lane from running.

## Foundational scientific corpus

The modern literature lane rotates across Orchidaceae-specific and general plant-science domains:

- orchid pollination and floral biology
- orchid mycorrhiza and fungal relationships
- orchid traits and ecology
- plant respiration and photosynthesis
- water relations and stomatal physiology
- mineral nutrition
- hormone signaling and development
- genetics, genomics, transcriptomics, and epigenetics
- cell and molecular biology
- biochemistry, metabolomics, proteomics, and secondary metabolism
- pigments and plant chemistry
- reproductive biology
- plant-fungal interactions
- evolution, ecology, adaptation, and phylogeny
- conservation, restoration, and reintroduction
- chromatography, spectroscopy, microscopy, and analytical methods

At the default 15-minute harvest interval the full 16-topic modern corpus rotates approximately every four hours. Topic selection is deterministic by time bucket, so restarts do not require another state table.

## Scholarly metadata and DOI reconciliation

Crossref is now a second modern literature provider. It runs every second normal harvest cycle and searches a bibliographic topic rotation aligned with the Europe PMC corpus. Crossref work records are staged as `SCIENTIFIC_LITERATURE_METADATA` with stable DOI-centered identities, authors, container/journal title, publication date, subjects, URL, work type, reference count, and citation count when supplied by Crossref.

Crossref records are metadata evidence rather than article full text. They are review-bound and cannot mutate the canonical knowledge graph automatically. `CROSSREF_MAILTO` is optional and, when configured, is sent with API requests and identified in the user agent.

## Historical books and monographs

BHL is now connected as a periodic historical-literature discovery lane. It uses the current BHL API v3 `PublicationSearch` operation with catalog + full-text search and stages bibliographic records into the semantic research index as `HISTORICAL_BOTANICAL_LITERATURE`.

The BHL topic rotation explicitly includes:

- Charles Darwin orchid fertilisation literature
- orchid pollination
- Orchidaceae
- orchid mycorrhiza
- orchid physiology
- plant physiology
- botanical morphology
- orchid monographs

Historical records remain metadata-only until a later bounded OCR/full-text acquisition step is explicitly implemented. This avoids accidentally treating catalog metadata as source text. BHL execution is enabled only when `BHL_API_KEY` exists in the deployment environment; otherwise runtime telemetry reports `not_configured` rather than failing the modern literature lane.

## GBIF completeness correction

The legacy production GBIF worker used `mediaType=StillImage`, which meant it harvested only GBIF occurrence records carrying still-image media. That was useful for image acquisition but incomplete for occurrence coverage.

The adaptive worker now uses `harvesters/gbif_global_api.py` with no media filter. It harvests all Orchidaceae occurrence records returned by the global GBIF occurrence store and extracts images opportunistically when media are present. A new checkpoint key (`gbif_global_v2`) prevents the old filtered-stream offset from being incorrectly reused against the broader global stream.

GBIF's synchronous occurrence search has a documented hard limit of 100,000 records per query. The new worker respects that boundary and reports `bulk_download_required` when it reaches it. It does not partition queries to evade the limit. Complete historical GBIF acquisition beyond the search ceiling must use GBIF's authenticated asynchronous Download API.

## Evidence governance

Discovered literature is staged as scientific literature evidence for Calyx, Brain, and Research Station consumers. Imported abstracts, scholarly metadata, and historical bibliographic records remain unverified research evidence and retain source identifiers/provenance. They are not promoted automatically to canonical scientific claims.

This preserves the core rule:

> Discovery is not truth. Literature becomes evidence first; claims require provenance, reconciliation, and review before canonical graph promotion.

## Why literature runs first

GBIF and other biodiversity backfills can remain productive for months or years. A sequential "finish source A before source B" architecture would therefore make literature acquisition indefinitely postponable. Running literature first establishes a fairness guarantee: every harvest cycle has an opportunity to improve scientific reasoning capacity before bulk biodiversity work consumes the remaining cycle.

## Implemented components

- `runtime/literature_harvester.py` — bounded rotating Europe PMC corpus harvester, Crossref metadata lane, and periodic BHL discovery
- `app/calyx_conversation/literature_ingest.py` — governed Europe PMC abstract indexing
- `app/calyx_conversation/scholarly_metadata_ingest.py` — governed Crossref DOI/scholarly metadata indexing
- `app/calyx_conversation/historical_literature_ingest.py` — governed BHL metadata indexing
- `adaptive_harvest_worker.py` — two-lane scheduler with literature first and global GBIF fallback
- `harvesters/gbif_global_api.py` — unfiltered global Orchidaceae occurrence/media stream with a separate checkpoint
- `app/routers/harvesters.py` — read-only `/api/harvesters/runtime-status` production observability endpoint
- `tests/test_literature_harvest_lane.py` — rotation, Crossref/BHL gating, ordering, failure isolation, and GBIF fall-through tests

## Validation

GitHub Actions completed both `BUILD-091 Validation` and `CALYX Certification Hardening 002` successfully for the first Crossref-enabled implementation commit (`c7956b24b4534ecb945ea59f7fee9cf7cc1f966a`). Additional focused Crossref mocked-network tests were subsequently added and are expected to run through the same push validations.

## Remaining high-priority work

1. Configure `BHL_API_KEY` in production if it is not already present, then verify live historical-book discovery.
2. Add bounded BHL OCR/page-text acquisition for reviewed historical works, including Darwin's orchid books.
3. Implement authenticated GBIF bulk Download API acquisition once credentials are supplied; this is required for complete historical GBIF coverage beyond 100,000 records.
4. Route reviewed pollination/mycorrhizal evidence into candidate graph relationships with source anchors.
5. Add complementary biodiversity publishers not fully represented in the GBIF aggregate.
6. Apply the existing BUILD-105 harvester-safety migration through an authorized database migration path so production safety snapshots stop reporting the missing-table warning.

The scheduler must preserve lane fairness as new source adapters are added; adding a high-volume source must never make literature optional or unreachable.
