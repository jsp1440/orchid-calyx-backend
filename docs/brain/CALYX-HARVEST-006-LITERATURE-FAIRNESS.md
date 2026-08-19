# CALYX-HARVEST-006 — Literature, Interaction, and Biodiversity Fairness

Status: implemented on `main`

## Decision

Scientific acquisition is divided into independent bounded lanes. High-volume occurrence/image work must never make literature, historical texts, or ecological-interaction discovery unreachable.

The in-process Calyx harvester therefore executes scientific-evidence work before the adaptive biodiversity backfill while keeping failures isolated between lanes.

## Production cycle

1. Literature lane — guaranteed every cycle
   - Europe PMC abstract discovery every cycle
   - Crossref DOI/scholarly metadata discovery every second cycle
   - Biodiversity Heritage Library bibliographic discovery every fourth cycle when `BHL_API_KEY` is configured
   - bounded BHL page/OCR acquisition every eighth cycle when `BHL_API_KEY` is configured
   - stable/idempotent research indexing
   - no automatic publication or canonical graph mutation
2. Interaction-discovery lane — checked every cycle, network work due every fourth cycle
   - Global Biotic Interactions live API exploratory discovery
   - alternates Orchidaceae as source and target taxon
   - includes child taxa through GloBI's normal taxonomic expansion
   - source/target taxa, interaction type, and study/dataset provenance retained
   - review-only semantic evidence; no automatic graph edge creation
3. Biodiversity lane
   - iNaturalist freshness
   - global GBIF Orchidaceae occurrence stream without an image-only filter
   - EOL/TraitBank fallback

Failure in any lane does not suppress the others.

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

At the default 15-minute harvest interval the full 16-topic Europe PMC corpus rotates approximately every four hours. Topic selection is deterministic by time bucket, so restarts do not require another scheduling table.

## Scholarly identity and DOI reconciliation

Europe PMC and Crossref evidence now carry a shared `canonical_publication_key`.

Identity preference is:

1. normalized DOI (`doi:<lowercase DOI>`)
2. PMID for Europe PMC records without DOI
3. PMCID for Europe PMC records without DOI/PMID
4. normalized-title SHA-256 fallback

This does not merge or discard provider-specific records. It creates an explicit cross-provider identity bridge so Crossref metadata and Europe PMC abstract evidence for the same publication can be reconciled downstream without relying on title guesses.

Crossref remains metadata evidence rather than article full text. It is review-bound and cannot mutate the canonical knowledge graph automatically. `CROSSREF_MAILTO` is optional and, when configured, is sent with Crossref requests and identified in the user agent.

## Historical books, Darwin, and BHL OCR

BHL bibliographic discovery uses `PublicationSearch` and explicitly rotates through:

- Charles Darwin orchid fertilisation literature
- orchid pollination
- Orchidaceae
- orchid mycorrhiza
- orchid physiology
- plant physiology
- botanical morphology
- orchid monographs

A second bounded BHL path now performs full-text page discovery. It uses BHL page search and hydrates at most two page records per due cycle with page OCR. Pages are indexed as `HISTORICAL_BOTANICAL_FULLTEXT` with:

- exact BHL page identifiers and locators
- `VERBATIM` representation
- limited-preview display policy
- retained rights/license metadata when supplied
- review required
- no automatic publication
- no direct knowledge-graph mutation

Page acquisition is query-targeted rather than downloading an entire book into the web process. This keeps Darwin and other historical works usable by Calyx while bounding network, memory, and indexing work.

BHL execution requires `BHL_API_KEY`. Missing credentials produce `not_configured` telemetry and do not block other literature sources.

## Ecological interactions and GloBI

Calyx now has a separate GloBI discovery lane rather than waiting for interaction evidence to emerge accidentally from image/occurrence processing.

The live GloBI API is used conservatively for freshness and candidate discovery. Requests are bounded, use `includeObservations=true`, retain study/source citation fields, and alternate queries where Orchidaceae is the source versus target taxon. GloBI child-taxon expansion is intentionally retained so family-level Orchidaceae queries can surface species-level interactions.

GloBI itself recommends its stable versioned integrated data product for research/data-intensive use. Therefore live API results are marked `LIVE_EXPLORATORY_API` and `stable_research_snapshot_preferred=True`. They enter the Brain as review-bound ecological-interaction discovery records rather than canonical graph edges. A future bulk GloBI snapshot import should reconcile these discoveries against the stable versioned dataset before publication.

The existing TIG live-source layer already recognizes `oc_globi.interactions`, `oc_pollination.interactions`, and other canonical interaction tables. The new lane improves discovery coverage without bypassing that governed path.

## GBIF completeness correction

The legacy production GBIF worker used `mediaType=StillImage`, so it harvested only occurrence records carrying still-image media. That was useful for image acquisition but incomplete for occurrence coverage.

The adaptive worker now uses `harvesters/gbif_global_api.py` without a media filter. It harvests Orchidaceae occurrences from the global GBIF occurrence store and extracts images opportunistically. A separate checkpoint key (`gbif_global_v2`) prevents the old filtered-stream offset from being reused against the broader stream.

The synchronous occurrence-search worker stops at GBIF's 100,000-record search boundary and reports `bulk_download_required`. It does not partition requests to evade the boundary. Complete historical acquisition beyond that point requires GBIF's authenticated asynchronous Download API.

## Evidence governance

Discovery is not truth.

Modern abstracts, scholarly metadata, historical bibliographic records, historical OCR pages, and live interaction discoveries enter governed research evidence first. Source identifiers and provenance are retained. None of these lanes automatically promote scientific claims or graph relationships.

Literature extraction already supports an `ecological_interaction` normalized domain and candidate handoff. The next integration step is therefore not to invent a parallel graph-writing path; it is to feed reviewed/anchored harvested evidence through the existing extraction, canonical-identity, and candidate-knowledge boundary.

## Implemented components

- `runtime/literature_harvester.py` — Europe PMC, Crossref, BHL metadata, and bounded BHL OCR scheduling
- `runtime/interaction_harvester.py` — bounded GloBI exploratory interaction discovery
- `app/calyx_conversation/literature_ingest.py` — Europe PMC abstract indexing with canonical publication keys
- `app/calyx_conversation/scholarly_metadata_ingest.py` — Crossref metadata indexing with canonical publication keys
- `app/calyx_conversation/historical_literature_ingest.py` — BHL bibliographic indexing
- `app/calyx_conversation/historical_fulltext_ingest.py` — exact-anchor BHL page OCR indexing
- `app/calyx_conversation/interaction_discovery_ingest.py` — review-bound GloBI interaction indexing
- `adaptive_harvest_worker.py` — three-lane fairness scheduler and global GBIF fallback
- `harvesters/gbif_global_api.py` — unfiltered global Orchidaceae occurrence/media stream
- `app/routers/harvesters.py` — read-only `/api/harvesters/runtime-status` production observability endpoint
- `tests/test_literature_harvest_lane.py`
- `tests/test_historical_fulltext_ingest.py`
- `tests/test_interaction_harvester.py`
- `tests/test_publication_reconciliation_keys.py`

## Validation state

The cross-provider publication-key commit completed both `BUILD-091 Validation` and `CALYX Certification Hardening 002` successfully. Subsequent BHL OCR and GloBI focused tests were added and are running through the same push validation workflows.

## Remaining high-priority work

1. Configure `BHL_API_KEY` in production if absent and verify live BHL metadata/OCR cycles.
2. Feed reviewed harvested literature through the existing literature extraction/candidate handoff so pollination, mycorrhizal, trait, and other relationships can become source-anchored candidate graph knowledge.
3. Add reproducible GloBI stable-snapshot backfill and reconciliation against live discovery candidates.
4. Implement authenticated GBIF Download API acquisition after credentials are supplied; required for historical coverage beyond the synchronous-search ceiling.
5. Add complementary national/institutional biodiversity sources where their records or metadata are not fully represented through GBIF.
6. Apply the existing BUILD-105 harvester-safety migration through an authorized database migration path so safety snapshots persist instead of producing the current missing-table warning.

The fairness invariant is permanent: adding a high-volume source must never make literature or interaction discovery optional or unreachable.
