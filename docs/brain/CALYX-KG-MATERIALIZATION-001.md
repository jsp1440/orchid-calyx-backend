# CALYX-KG-MATERIALIZATION-001 — Verified cross-domain graph materialization

## Why this exists

The executive audit can report millions of source records while still reporting taxonomy-to-domain relationships as missing. Canonical main already contains domain adapters, relational source corpora, graph publication infrastructure, staging validation, and a writable PostgreSQL graph repository. The missing operational bridge was a governed path that materializes verified relationships and a retrieval layer that actually lets Calyx consume the resulting scientific fabric.

## Live production baseline — 2026-08-12

Read-only Render-shell measurement established that `oc_graph` is real and populated but only partially materialized:

- 37,641 graph nodes
- 70,602 graph edges
- 33,878 taxon nodes
- 2,807 trait nodes
- 115 pollinator nodes
- 51 image nodes
- 29 publication nodes
- 26 occurrence nodes
- 2 conservation-assessment nodes

Live source discovery then established the much larger underlying corpora, including 580,612 `public.orchid_occurrence` rows, 19,929 normalized trait-consensus rows, 6,725 `public.research_documents` rows, 695 habitat claims, and millions of general records. Therefore predicate presence is not accepted as evidence of corpus-complete graph integration.

## Materialization architecture

`runtime/knowledge_graph/production_materializer.py` connects verified source projections to canonical domain adapters and reuses the controlled two-pass staging engine and single-writer transactional production publisher. Production requires an explicit domain list and exact confirmation token `PUBLISH_VERIFIED_GRAPH_RELATIONSHIPS`; failed or unhealthy runs roll back and are never reported as successful mutation.

Verified live-source corrections include the bulk occurrence and trait corpora plus verified habitat/elevation projections. Occurrence nodes retain geographic/environmental evidence such as latitude, longitude, point/min/max elevation, country, region, locality, habitat/climate context, and provenance. Raw occurrence-level elevation remains observational evidence; derived taxon elevation profiles are a separate semantic layer.

`runtime/knowledge_graph/source_coverage_audit.py` measures authoritative source rows, taxon-resolved rows, persisted graph nodes/edges, and coverage ratios. A tiny graph subset can no longer masquerade as an integrated domain simply because an edge type exists.

## Scientific-method evidence graph

The literature extraction subsystem already models `PaperKnowledge` sections, entities, measurements, claims, evidence spans, normalized evidence records, relationships, figures, tables, references, review decisions, publication decisions, and exact provenance. The graph vocabulary therefore includes observations, hypotheses, methods/protocols/experiments, measurements/datasets, results, conclusions, limitations, recommendations, citations/references, sections, figure/table evidence, and their evidence relationships.

The governed `runtime/knowledge_graph/paper_knowledge_graph.py` mapper preserves those distinctions and omits unreviewed scientific claims by default. Vocabulary definition and mapping do not themselves authorize production publication.

## Retrieval-side integration completed in this branch

### Explicit taxon graph context

Calyx resolves explicit binomial names by exact persisted taxon identity and performs bounded read-only graph traversal. It does not perform fuzzy identification in this path.

### Occurrence geography/elevation queries

`app/calyx_conversation/occurrence_query.py` converts a narrow, auditable class of questions such as `orchids in Ecuador above 3000 m` into parameterized read-only queries over `public.orchid_occurrence`, with every returned species anchored back to an active persisted KG taxon node. Above, below, between, and exact/around metric elevation constraints are supported. A truthful zero result is preserved rather than replaced by inference.

### Literature corpus bridge

`app/calyx_conversation/graph_literature_search.py` keeps persisted graph publications as the primary route, then searches `public.research_documents` for exact-binomial literal matches when graph coverage is incomplete. Literal matches are explicitly discovery metadata, not inferred `documented_by` edges or scientific claims.

### Reviewed extraction evidence

Canonical source bindings already connected a `LITERATURE_DOCUMENT` source object to exact `PaperKnowledge` extraction evidence and source anchors. The branch adds the reverse read path and `app/calyx_conversation/extracted_literature_evidence.py`, which revalidates source integrity and exposes only normalized records whose recorded publication decision is `eligible_for_publication`. Calyx therefore distinguishes persisted graph relationships, literal document discovery, publication-eligible normalized evidence, and higher-level synthesis.

The deterministic fallback and optional configured provider both preserve those epistemic boundaries. Calyx can surface reviewed evidence even while the semantic evidence index is degraded, but it does not promote document titles, literal mentions, graph connectivity, or occurrence observations into unsupported causal conclusions.

## Governance

No production Knowledge Graph mutation has occurred on this branch. Read-only graph traversal, source-corpus inventory, occurrence constraint queries, literature discovery, and reviewed extraction retrieval do not activate taxonomy, publish Candidate Knowledge, change review state, or mutate the graph.

Production graph publication remains owner-governed and must occur only after trusted validation, one verified slice at a time, with persisted audit between slices.

## Validation state

Focused regression coverage now includes bulk source selection, materialization governance, source coverage, scientific-method vocabulary/mapping, explicit occurrence parsing and rendering, exact-binomial document discovery, canonical source-binding reverse lookup, source-integrity revalidation, publication-eligible evidence retrieval, and provider provenance rendering.

The dedicated `.github/workflows/calyx-kg-bulk-source-validation.yml` includes these integration files in compile, pytest, Ruff, and diff-hygiene checks. GitHub-hosted Actions is still affected by the runner allocation incident: recent jobs have been created with `steps:null`, so no checkout or validation commands executed. Zero-step runs are not accepted as validation evidence.

## Next operational gate

1. Obtain executable exact-head validation through a functioning runner or trusted environment.
2. Run bounded read-only live acceptance for corrected occurrence/trait/habitat/elevation source projections and the Calyx occurrence/literature retrieval slices.
3. Repair any live schema or source-binding mismatch found by that proof.
4. Only with owner authorization, materialize verified graph domains one at a time and re-run persisted graph integrity/coverage audits after each slice.
5. Continue scientific-method materialization for reviewed `PaperKnowledge` entities/evidence while preserving source anchors, review state, and publication governance.
