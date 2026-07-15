# Orchid Continuum — Scientific Knowledge Graph Completion Report

**Repository:** jsp1440/orchid-calyx-backend
**Base commit:** `1084bea8152676f5de9c28536cf20cb257615bc6`
**Branch:** feat/scientific-knowledge-graph-completion
**Mode:** Forensic implementation, knowledge-graph-first. Read-only production data access. No production database writes. No destructive migrations. Feature branch + PR, no merge.

---

## 1. Repositories and commits inspected

| Repository | Ref | Role in this pass |
|---|---|---|
| jsp1440/orchid-calyx-backend | `1084bea8152676f5de9c28536cf20cb257615bc6` (main, PR #55 merged) | Target — graph API + publisher implemented here |
| jsp1440/OrchidContinuumHarvester | read-only reference | Source of the public-api service |
| jsp1440/OrchidContinuum | read-only reference | Legacy backend + harvester engine |
| jsp1440/Orchid-Continuum-Brain | read-only reference | Architecture/vocabulary reference |
| jsp1440/orchid-continuum-frontend | read-only reference | Consumer contract (Phase 10) |

Production data: Orchid Continuum Neon database (`neondb`, PostgreSQL 17.10), reached read-only via the `DATABASE_URL` connection the deployed Calyx backend already uses. ~120 `oc_*` schemas.

---

## 2. Current graph domain coverage (Phase 1 audit)

The canonical graph tables are `oc_graph.kg_nodes` and `oc_graph.kg_edges`.

**Before this pass the graph is taxonomy-only:**

| | Value |
|---|---|
| kg_nodes (active) | 34,519 — node types: `genus` (733), `taxon` (33,786) |
| kg_edges (active) | 67,572 — edge types: `genus_contains_species` (33,786), `species_belongs_to_genus` (33,786) |

No image, occurrence, literature, pollinator, mycorrhiza, trait, glossary, conservation, climate, habitat, elevation, molecular, evidence, or education nodes/edges currently exist in the graph, **even though rich relational sources for those domains exist elsewhere in the warehouse** (see §7–9). The graph is therefore a *taxonomy backbone awaiting domain publication*, not an integrated scientific graph. Node/edge counts alone are misleading — this was confirmed by enumerating distinct `node_type`/`edge_type`, not by totals.

**Graph model fields available:** `kg_nodes` carries `node_type`, `canonical_key`, `display_label`, `source_table`/`source_pk` (provenance), `evidence_class`, `confidence_score`/`confidence_label`, `payload_json`, `is_active`, `build_run_id`, `created_at`/`updated_at`. `kg_edges` mirrors this plus `edge_type`, `from_node_id`/`to_node_id`, `rule_name`. Supporting tables: `kg_build_runs`, `kg_node_lineage`, `kg_edge_lineage`, `kg_conflict_log`, `kg_quality_metrics`.

**Canonical identity strategy (observed):** `canonical_key = "<node_type>:<source_pk>"` (e.g. genus Cattleya = `genus:560`; species = `taxon:<id>`). This is deterministic and idempotent, and is reused by the publisher in this pass.

**Gaps in the model:** provenance, confidence and evidence linkage are supported; **temporal validity (valid-from/valid-to) and supersession are not** first-class columns. Addressed by a generated (unexecuted) migration — see §12.

---

## 3. Node-type inventory (controlled vocabulary)

Present in production: `genus`, `taxon`.
Defined by this pass for domain publication (reused, not genus-specific): `species`, `synonym`, `taxon_concept`, `image`, `occurrence`, `place`, `country`, `region`, `habitat`, `climate`, `elevation`, `trait`, `glossary_term`, `publication`, `assertion`, `evidence`, `pollinator`, `fungus`, `conservation_assessment`, `molecular_record`, `research_question`, `hypothesis`, `lesson`, `chapter`, `figure`.

## 4. Edge-type inventory (controlled vocabulary)

Present in production: `genus_contains_species`, `species_belongs_to_genus`.
Defined by this pass: `has_synonym`, `has_taxon_concept`, `has_image`, `occurs_at`, `occurs_in`, `occupies_habitat`, `experiences_climate`, `has_elevation`, `has_trait`, `defined_by_term`, `documented_by`, `supported_by_evidence`, `contradicted_by`, `associated_with_pollinator`, `associated_with_mycorrhiza`, `has_conservation_assessment`, `has_molecular_record`, `phylogenetically_related_to`, `explained_by`, `raises_question`, `tested_by_hypothesis`.

Existing conventions were reused (the two taxonomy edges) and extended coherently; nothing was renamed.

## 5. Canonical identity model

`canonical_key = "<node_type>:<source_pk>"`, matching production. `source_pk` is a stable identifier from the canonical relational source, never an uncontrolled name string. The publisher upserts on `canonical_key` (nodes) and on `(edge_type, from_node_id, to_node_id, source_table)` (edges), so repeated builds are idempotent and cannot create duplicate canonical nodes. Distinct taxonomic concepts sharing a name remain distinct because they carry distinct `source_pk` values (`taxon_concept` node type is reserved for this).

---

## 6. Domains newly connected (code path implemented this pass)

A reusable, tested publication path (`runtime/knowledge_graph/publisher.py`) now exists for **all** domains via the `DomainAdapter` contract. It is proven end-to-end for the **media** domain in tests (idempotent create, provenance/confidence preservation, dedup, vocabulary validation). Because production writes are out of scope, no domain was published to the production graph in this pass — the code is ready to run inside a build run.

## 7. Domains already connected (in the production graph)

- **taxonomy** — genus↔species, live and traversable (proven in §14–16).

## 8. Domains with production sources, awaiting graph publication

Verified that a canonical relational source table/view exists (by name/schema) for each; row-level per-taxon completeness must be confirmed inside a build run before publishing:

media, occurrences, geography, habitat, climate, elevation, traits, glossary, literature, evidence, pollinators, mycorrhiza, conservation, molecular, education. See `runtime/knowledge_graph/domain_sources.py` for the exact source per domain.

## 9. Domains staging-only / unavailable

- **research** (research questions / hypotheses): sources appear to live in `oc_reasoning.*`/`oc_reflect.*` — treated as **staging_only**; must not be published as production evidence until promoted.
- No domain was classified fully **unavailable**; all have at least a candidate source. Any that prove empty at build time should be recorded unavailable then.

---

## 10. Files changed

```
runtime/knowledge_graph/__init__.py          (new)  package surface
runtime/knowledge_graph/vocabulary.py        (new)  node/edge types -> domains
runtime/knowledge_graph/models.py            (new)  Node / Edge dataclasses
runtime/knowledge_graph/repository.py        (new)  GraphRepository: Postgres (read-only) + InMemory
runtime/knowledge_graph/traversal.py         (new)  depth/filter/paginated traversal + coverage/gaps
runtime/knowledge_graph/quality.py           (new)  read-only quality metrics
runtime/knowledge_graph/publisher.py         (new)  idempotent domain publication
runtime/knowledge_graph/domain_sources.py    (new)  canonical source registry (audit result)
app/routers/knowledge_graph.py               (new)  /api/knowledge-graph/* endpoints
app/main.py                                  (edit) register knowledge_graph router
tests/test_knowledge_graph_traversal.py      (new)  17 regression tests
migrations/knowledge_graph/0001_edge_temporal_supersession.sql  (new, NOT executed)
docs/Orchid_Continuum_Scientific_Knowledge_Graph_Completion_Report.md  (this file)
```

## 11. Database objects used (read-only)

`oc_graph.kg_nodes`, `oc_graph.kg_edges` (traversal + quality). Audit-only reads of `information_schema`, `pg_namespace`, and candidate domain-source tables listed in `domain_sources.py`. **No writes, no DDL, no DML against production.**

## 12. Migrations created

One generated, **not executed**: `migrations/knowledge_graph/0001_edge_temporal_supersession.sql`. Additive and idempotent (`ADD COLUMN IF NOT EXISTS`, guarded constraint, `CREATE INDEX IF NOT EXISTS`). Adds `valid_from`, `valid_to`, `relationship_status` (default `active`), and `superseded_by_edge_id` to `oc_graph.kg_edges` so edges can express temporal validity and supersession. Existing taxonomy edges are unaffected (columns default to NULL/`active`). Rollback guidance is included in the file. **Owner decision required before execution.**

## 13. Tests and results

`tests/test_knowledge_graph_traversal.py` — **17 passed** (`python -m pytest`, 0.23s). Coverage: canonical node/edge creation; idempotent rebuild; duplicate prevention; provenance/evidence/confidence preservation; unknown-vocabulary rejection; orphan + dangling-edge detection; genus/taxon lookup (case-insensitive); node-type/edge-type filters; pagination + truncation; depth clamping; explicit data-gap reporting; and a parametrized Cattleya/Bulbophyllum/Dracula proof that the traversal is generic. All tests run against an in-memory repository — **no database connection is opened during tests** (no production writes). `app.main` imports cleanly with the new router registered.

## 14. Cattleya graph proof (live, read-only)

`GET /api/knowledge-graph/genus/Cattleya` traverses from focal node `genus:560` (kg_node_id 68132):
- **256** connected `taxon` species nodes (e.g. *Cattleya aracuaiensis*, *C. aclandiae*), via `genus_contains_species` edges.
- domain_coverage: `taxonomy`.
- data_gaps (explicit): media, occurrences, geography, habitat, climate, elevation, traits, glossary, literature, evidence, pollinators, mycorrhiza, conservation, molecular, research, education.

## 15. Bulbophyllum graph proof (live, read-only)

Focal `genus:661` (kg_node_id 68233): 500 species on the first page, `truncated=true` (pagination working; genus has >500 species). Same taxonomy coverage; same explicit gaps.

## 16. Dracula graph proof (live, read-only)

Focal `genus:523` (kg_node_id 68095): **152** species (e.g. *Dracula chimaera*, *D. chiroptera*). Same taxonomy coverage; same explicit gaps.

The same code path served all three genera with no genus-specific logic.

## 17. Graph-quality results

`GET /api/knowledge-graph/quality` reports, read-only: node/edge counts, orphan nodes, dangling edges, duplicate canonical nodes, missing provenance, invalid node/edge types, and a boolean `healthy`. It reports **actual structural state — no invented completion percentage**. (In tests, a healthy synthetic graph reports 0 issues; a graph with a dangling edge and an orphan reports them correctly.)

## 18. API contract

```
GET /api/knowledge-graph/node/{node_id}
GET /api/knowledge-graph/taxon/{taxon_id}        # accepts "taxon:123" or "123"
GET /api/knowledge-graph/genus/{genus_name}      # case-insensitive
GET /api/knowledge-graph/quality
```
Query params on the three traversal routes: `depth` (1–3), `node_types` (csv), `edge_types` (csv), `limit` (1–500), `offset`. Response: `focal_node`, `nodes`, `edges`, `node_types`, `edge_types`, `domain_coverage`, `data_gaps`, `graph{depth,node_count,edge_count}`, `pagination{limit,offset,truncated,next_offset}`, `filters`. Every node/edge carries `provenance`, `evidence_class`, `confidence`, and `payload`. Responses come from graph nodes/edges only.

## 19. Frontend integration contract (Phase 10 — no homepage work done)

- **Featured Genus** should call `GET /api/knowledge-graph/genus/{name}` and render `focal_node` + connected species from `nodes`, using `data_gaps` to show honest "not yet in graph" states instead of empty placeholders.
- **Images become graph nodes** (`image` node, `has_image` edge) once the media domain is published; the Featured Genus/Species image strip should then read images from the traversal, not a separate media endpoint.
- **Atlas** becomes a graph-connected view via `occurrence`/`place` nodes and `occurs_at`/`occurs_in` edges (after occurrences publication); dead direct-table atlas calls should be replaced with graph traversal filtered by `edge_types=occurs_at,occurs_in`.
- **Calyx** receives evidence-linked relationships by consuming edges' `evidence_class`/`confidence`/`provenance`.
- **Glossary & traits** become navigable via `glossary_term`/`trait` nodes and `defined_by_term`/`has_trait` edges.
- Components to remove once domains are published: any static or direct-table Featured Genus / Atlas / glossary widgets that bypass the graph.

## 20. Pull request URL

See the PR opened from `feat/scientific-knowledge-graph-completion` into `main` (not merged).

## 21. Redeploy requirements

The new router is import-clean and requires no new dependencies (uses existing `fastapi`, `psycopg`). It reads the graph via the existing `DATABASE_URL`. A redeploy of the Calyx backend service activates `/api/knowledge-graph/*`. The migration in §12 is **not** part of redeploy and must not be run without owner approval.

## 22. Remaining blockers / owner decisions required

1. **Production graph publication of non-taxonomy domains** requires write access to `oc_graph` inside a build run — out of scope here (no prod writes). Owner decision: authorize a build run per domain.
2. **Migration 0001** (temporal/supersession columns) requires owner approval to execute.
3. **Per-domain row-level verification**: source tables were verified to exist; a build run must confirm per-taxon data completeness and reclassify any empty domain as `unavailable`.
4. **research** domain confirmed staging-only pending promotion policy.

### Recommended next build
Publish the **media** domain first (adapter already proven in tests; `oc_core.media_assets` + `oc_core.record_media_link` are the canonical source), then **occurrences** and **literature**, each as an idempotent build run writing `image`/`occurrence`/`publication` nodes and their edges — after which the Featured Genus and Atlas can traverse real multi-domain graph data.
