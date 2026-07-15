# BUILD-066 — Full Scientific Knowledge Graph Population — Completion Report

**Branch:** `feat/scientific-knowledge-graph-completion` · **PR:** #56
**Mode executed:** `DRY_RUN` (full scope, all 8 domains) — **NO production writes.**
**Predecessors:** BUILD-060–065 (orchestrator, adapters, checkpointing, source
registry, validation, canonical World Plants backbone).

## What this build does
Populates **every** scientifically defensible production record into the
canonical Knowledge Graph by connecting it to the World Plants canonical taxon
backbone, reusing the existing orchestrator / publisher / repository /
checkpoint / source-registry / validation / canonical-taxonomy infrastructure.
No new repository, no redesign. Records that cannot be mapped are routed to
documented review queues and **never discarded**. Domains populate
independently — a gap in one never blocks another.

## Execution posture (per operator decision)
A full-scope **DRY_RUN** was executed first: all domains projected into an
in-memory staging graph seeded read-only from the production taxon backbone.
`wrote_to_production = False`. The projected counts below are what a real
`PUBLISH` (authorized) would write. **Awaiting explicit approval before any
production publish.**

## Headline projected result (DRY_RUN)
| Metric | Value |
|---|---|
| Domains populated | 8 / 8 |
| Nodes projected | **22,492** |
| Edges projected | **22,827** |
| Invalid rows rejected | 0 |
| Orphan edges (unresolved endpoint) | 0 |
| Canonical taxa in backbone | 33,786 |
| Taxa connected to ≥1 domain | **20,038** |
| Taxa fully unconnected | 13,748 |
| **Overall graph completion** | **59.31 %** |
| Review-queue items | 699 |
| Duration | 42.2 s |

## Infrastructure changes (small, reuse-only)
- `PostgresGraphRepository.taxonomy_nodes()` — targeted `taxon`/`genus` fetch so
  DRY_RUN staging seeds without streaming the entire production graph.
- `InMemoryGraphRepository` — added O(1) key/edge indexes; full-scale staging
  population dropped from >10 min to ~42 s. Behaviour unchanged (116 tests pass).
- `runtime/knowledge_graph/reporting.py` — reusable, side-effect-free report
  generators (domain coverage, graph completeness, review queues).
- `BuildOrchestrator.last_target_repo` — exposes the produced staging/prod graph
  for introspection by reporting.

## Deliverables
1. `01-full-population-report.md` — Full Graph Population Report
2. `02-domain-coverage-report.md` — Domain Coverage Report
3. `03-graph-completeness-report.md` — Graph Completeness Report
4. `04-unconnected-records-report.md` — Unconnected Records Report
5. `05-review-queue-report.md` — Review Queue Report
6. `06-operator-guide.md` — Updated Operator Guide (full population / resume / publish)
7. `07-test-results.md` — Updated Test Results
8. This completion report + final verdict (bottom).

Machine-readable artifacts: `full_population_report.json`,
`domain_coverage_report.json`, `graph_completeness_aggregate.json`,
`graph_completeness_per_taxon.csv`, `unconnected_records_report.json`,
`review_queue_report.json`, `build066_summary.json`.

## ⚠️ Decision-critical findings before publish
1. **Climate dominates coverage but is proxy data.** `climate` contributes
   19,263 of 22,827 edges (57 % of all coverage) yet is registry status
   **BLOCKED / confidence low**: `species_environment_profile` is an
   *occurrence-derived environmental proxy* (elevation bounds, bbox, qualitative
   `climate_proxy_zones`), **not modelled bioclim**. Publishing it as
   `experiences_climate` edges materially inflates completion. **Recommend
   withholding climate from the first production publish** (or publishing it
   under an explicit "proxy" provenance) pending the true-bioclim derivation.
2. **Mycorrhiza name-collision fan-out.** 462 source rows inflate to 626 edges
   because 32 scientific names collide with >1 backbone node (name_join). Some
   edges therefore attach an association to more than one taxon. Flagged for
   review; crosswalk upgrade recommended before publish.
3. **Large documented source gaps are expected, not errors** — see the
   Unconnected Records Report (e.g. 579,974 bulk occurrence rows on an
   unverified alt-source linkage; 30,984 taxa without trait consensus).

## Final verdict
See bottom of this report / PR #56 comment.
