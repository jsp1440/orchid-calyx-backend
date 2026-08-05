# Calyx Graph Pipeline Core Readiness

## Contract

The machine-readable contract is `calyx-graph-pipeline-core-readiness-v1`.
It is available through both:

- `GET /api/mission-control/graph-pipeline/readiness` (owner/API-key gated);
- `python scripts/report_graph_pipeline_readiness.py` (local JSON report).

Both paths are read-only. They do not import source data, authorize publication,
or mutate the production graph. Live counts are reported only when a read-only
observer supplies them. Otherwise the count is `null` with a reason. Local
World Plants inspection reports and local literature extraction artifacts are
counted because those observations require no external writes or production
database access.

## Executable-evidence inventory

This assessment was derived from callable code and its tests, not from build
status prose. The contract lists the exact executable components per domain.

| Stage | Taxonomy (Hassler / World Plants) | Occurrences | Licensed images | Literature evidence |
|---|---|---|---|---|
| Source ingestion | `parse_world_orchids_release`; bounded upload endpoint | GBIF and iNaturalist paged clients; `HarvestManager(max_pages=...)` | GBIF/iNaturalist image extraction inside bounded occurrence pages | CLI accepts a local UTF-8 text file |
| Raw persistence | Immutable local source bytes and report | Only `InMemoryHarvestPersistence` in Harvester V2 | Only `InMemoryHarvestPersistence` in Harvester V2 | Atomic local `raw.txt`, `paper.json`, manifest and metrics |
| Normalization | 22-field parser and synonym parser | Source-specific canonical harvest shapes | Licensed media fields normalized with source identifiers | Metadata, sections, entities, claims, evidence, normalization and review queue |
| Taxonomic reconciliation | Deterministic release delta/crosswalk and canonical-registry builder; review gated | Missing external source-id to canonical taxon-id bridge | Candidate builder requires existing canonical record-media links | Graph source uses exact scientific-name join because source lacks canonical taxon id |
| Provenance | Snapshot checksum, source system, version and acquisition time | Source and raw record retained, but no durable production sink | Provider, provider record id and license in verified candidate provenance | Source spans, manifests, hashes, source binding and evidence anchors |
| Staging graph projection | No inspected-release-to-staging executable job | Registered `occurrences_v1` query, adapter and staging orchestrator | Registered `media_gallery_v1` query, adapter and staging orchestrator | Registered `literature_taxon_edges_v1` query, adapter and staging orchestrator |
| Publication readiness | Blocked before staging projection and owner promotion | Blocked before durable persistence and canonical reconciliation | Blocked before durable media persistence/link bridge | Blocked before canonical-id handoff |
| Freshness/checkpoint | Intake reports exist; no scheduled release freshness checkpoint | Checkpoint protocol exists, but production implementation is in-memory only | Same occurrence-harvest checkpoint limitation | No resumable ingestion checkpoint |
| Mission Control | Taxonomy readiness and release inspection routes | Harvester telemetry/control-plane visibility, not vertical graph readiness | Harvester telemetry only | Paper lookup/source binding endpoints, not vertical graph readiness |

## Domain status and blockers

### Taxonomy — partial

Executable intake, immutable local raw persistence, parsing, release comparison,
synonym parsing, canonical registry construction, and Mission Control inspection
exist. It is not operational because no executable job projects an inspected
release into a staging graph and no executable promotion job binds the reviewed
release to the canonical graph backbone.

Exact next executable job: `python scripts/smoke_world_plants_activation.py`.
This uses the harmless bounded fixture and does not promote a release.

### Occurrences — partial

GBIF and iNaturalist page ingestion, normalization, page bounds, in-memory
checkpoints, a registered relational source query, a graph adapter, and staging
orchestration exist. It is not operational because Harvester V2 has no durable
production persistence/checkpoint adapter and the upstream GBIF/iNaturalist
taxon identifiers are not reconciled to the canonical `taxon_id` required by
`oc_atlas.occurrences` and the graph source projection.

Exact next executable job: `python scripts/run_bounded_resumable_graph_dry_run.py`.
It processes one domain, one batch of at most 100 rows, in staging only.

### Licensed images — partial

GBIF and iNaturalist emit license-bearing normalized image records. The exact-ID
taxonomy/image candidate builder records provider and license provenance. The
media graph source and adapter are registered. It is not operational because no
durable executable persists harvested images into the `oc_core` media relations,
and no executable connects those records through verified canonical
record-media links to the registered gallery projection.

Exact next executable job: `python scripts/run_bounded_resumable_graph_dry_run.py`.

### Literature evidence — partial

Local text ingestion, atomic raw/output persistence, extraction, normalization,
provenance, review, canonical source binding, candidate handoff, graph source,
and graph adapter exist. It is not operational because DOI/URL fetching is not
wired into the executable CLI/API, literature graph rows lack canonical taxon
ids and rely on a name join, and no freshness/checkpoint job exists.

Exact next executable job:
`python -m app.literature_extraction tests/fixtures/literature/calyx_brain_001_orchid_study.txt --output /tmp/calyx-literature-bounded`.

## Prioritized vertical plan

1. **Taxonomy:** run the bounded activation smoke; implement a resumable,
   owner-reviewed inspected-release-to-staging projection; validate; then add a
   separately authorized promotion job.
2. **Occurrences:** implement durable raw/normalized persistence and durable
   checkpoints; add GBIF/iNaturalist-to-World-Plants crosswalk output; populate a
   bounded staging slice; validate the registered occurrence adapter.
3. **Licensed images:** reuse the occurrence persistence/checkpoint path; enforce
   license allowlisting; persist media assets and canonical record-media links;
   validate a bounded gallery projection.
4. **Literature:** add bounded DOI/URL acquisition with source checkpoints;
   persist canonical taxon ids during reviewed handoff; replace the name-only
   graph join; validate a bounded literature projection.
5. Surface this unified contract in Mission Control as the single vertical
   source-to-visible-graph readiness view. The endpoint added here supplies the
   backend contract; frontend rendering is intentionally outside this backend
   track.

## First safe bounded production job after merge

Run `python scripts/smoke_world_plants_activation.py` with the deployed backend
URL and owner credentials. It uploads only the repository's one-row activation
fixture to the non-promoting inspection endpoint. Stop after verifying the
readback report. Do not invoke publication or an unbounded import.
