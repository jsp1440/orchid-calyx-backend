# CALYX-HARVEST-006 — Literature Fairness and Scientific Corpus Lane

Status: implemented on `main`

## Decision

Literature acquisition is a first-class scientific lane and must not depend on occurrence, image, or trait backfills reaching an exhausted state.

The in-process Calyx harvester now executes a bounded literature task before the adaptive biodiversity task on every cycle. This prevents long-running iNaturalist/GBIF/image work from starving the Brain and knowledge systems of scientific literature.

## Production cycle

1. Literature lane (guaranteed first)
   - Europe PMC discovery
   - maximum 5 records per default cycle
   - stable/idempotent research indexing
   - review-bound evidence only
   - no automatic publication
   - no direct canonical knowledge-graph mutation
2. Biodiversity lane
   - iNaturalist
   - GBIF fallback
   - EOL/TraitBank fallback

Failure in either lane does not prevent the other lane from running.

## Foundational scientific corpus

The literature lane rotates across Orchidaceae-specific and general plant-science domains:

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

At the default 15-minute harvest interval the full 16-topic corpus rotates approximately every four hours. Topic selection is deterministic by time bucket, so restarts do not require another state table.

## Evidence governance

Discovered literature is staged as scientific literature evidence for Calyx, Brain, and Research Station consumers. Imported abstracts remain unverified research evidence and retain source identifiers/provenance. They are not promoted automatically to canonical scientific claims.

This preserves the core rule:

> Discovery is not truth. Literature becomes evidence first; claims require provenance, reconciliation, and review before canonical graph promotion.

## Why literature runs first

GBIF and other biodiversity backfills can remain productive for months or years. A sequential "finish source A before source B" architecture would therefore make literature acquisition indefinitely postponable. Running literature first establishes a fairness guarantee: every harvest cycle has an opportunity to improve scientific reasoning capacity before bulk biodiversity work consumes the remaining cycle.

## Implemented components

- `runtime/literature_harvester.py` — bounded rotating Europe PMC corpus harvester
- `adaptive_harvest_worker.py` — two-lane scheduler with literature first
- `tests/test_literature_harvest_lane.py` — rotation, ordering, failure-isolation, and biodiversity fall-through tests

## Next expansion priorities

1. Historical books and monographs: Biodiversity Heritage Library / other lawful public-domain sources, including Darwin's orchid works.
2. DOI/metadata reconciliation: Crossref and related scholarly metadata sources.
3. Dedicated pollination/mycorrhizal relationship extraction into candidate graph edges.
4. GBIF bulk historical backfill separated from incremental freshness polling.
5. Additional biodiversity publishers not fully represented through the GBIF aggregate.

The scheduler must preserve lane fairness as new source adapters are added; adding a high-volume source must never make literature optional or unreachable.
