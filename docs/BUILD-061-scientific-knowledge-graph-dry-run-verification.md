# BUILD-061 — Scientific Knowledge Graph Dry-Run Verification Report

**Repository:** jsp1440/orchid-calyx-backend
**Branch:** `feat/scientific-knowledge-graph-completion` (PR #56, open — NOT merged)
**Verified commit:** `1897a53b` (BUILD-060)
**Mode:** Read-only forensic verification. No production writes. No migrations. No publish. No merge. No architecture change.
**Production DB observed:** `neondb`, PostgreSQL 17.10 (read-only `SELECT` / `information_schema` only)

---

## 0. Recommendation

**NOT READY FOR PRODUCTION POPULATION.**

BUILD-060's orchestrator, adapters, checkpointing and validation are correctly
implemented and behave exactly as specified (AUDIT/DRY_RUN safe, PUBLISH/RESUME
gated). **However, no domain adapter is connected to real production source
data.** The connection layer (`PostgresSourceProvider`) requires an
operator-supplied per-domain read-only projection SQL (`queries` dict) that maps
each source table's columns to the publisher contract (`source_pk`, `taxon_pk`,
plus field columns). **That SQL does not exist anywhere in the repository for any
domain**, and three of the eight adapters name source tables that do not exist in
production. A dry run today therefore reads **zero** real records and projects
**zero** graph growth. Evidence follows.

---

## 1. Orchestrator verification (empirical)

Run against in-memory taxonomy + source fixtures (no DB opened):

| Check | Result | Evidence |
|---|---|---|
| AUDIT works | ✓ | Returns per-domain `source_availability`; `wrote_to_production=False` |
| DRY_RUN works | ✓ | Runs adapters into seeded in-memory staging; `wrote_to_production=False` |
| PUBLISH disabled without authorization | ✓ | `wrote_to_production=False`; warning "PUBLISH requested without authorization; no writes performed." |
| RESUME disabled without authorization | ✓ | `wrote_to_production=False`; warning "RESUME requested without authorization; no writes performed." |
| Checkpoints created | ✓ | 8 checkpoints (one per domain), each `status=completed` in dry run |
| Batching works | ✓ | 5 fixture rows at `batch_size=2` → 3 batches, 5 nodes |
| No production writes | ✓ | Only AUDIT/DRY_RUN exercised; staging is a fresh in-memory repo seeded read-only from taxonomy |

The orchestrator is sound. The gap is entirely in **data connection**, not control logic.

---

## 2. Data-connection verification (the core finding)

### 2.1 How connection is supposed to work
- Adapters (`adapters.py`) map dict rows → `NodeSpec`/`EdgeSpec`. Each row **must**
  carry `source_pk` and `taxon_pk`; rows missing either are silently skipped.
- Rows are supplied by a `SourceProvider`. The live one, `PostgresSourceProvider`,
  is constructed with `queries: dict[domain -> SQL]`. It wraps each query as
  `SELECT * FROM (<query>) ORDER BY source_pk` — so each query **must** already
  alias its output columns to `source_pk`, `taxon_pk`, and the field names the
  adapter reads.

### 2.2 What actually exists
- **No `queries` dict is defined anywhere in the codebase.** Grep for
  `PostgresSourceProvider(...)` construction / `queries=` finds only the class
  definition and the exports — **no caller wires real SQL**. There is no CLI,
  script, or route that instantiates a live provider.
- `domain_sources.py` is **descriptive metadata only** (verified table names +
  intended vocabulary). Its own docstring states "importing it performs no I/O …
  descriptive metadata used by the report." It is **not** consumed by
  `PostgresSourceProvider` — the provider takes an explicit `queries` argument.
- Therefore every live AUDIT/DRY_RUN today would raise `KeyError: no read-only
  source query registered for domain` on first fetch, or (with an empty provider)
  read zero rows. Confirmed empirically: AUDIT availability is `0` for all eight
  domains.

### 2.3 Do the adapters' declared source tables even exist in production?
Read-only `information_schema` probe of the tables named in `adapters.py`:

| Adapter `source_table` | Production status |
|---|---|
| `oc_atlas.occurrences` | **EXISTS** (base table) |
| `oc_traits.traits` | **EXISTS** (base table) |
| `oc_conservation.conservation_records` | **EXISTS** (base table) |
| `oc_citations.literature_nodes` | **EXISTS** (base table) |
| `oc_core.media_assets` | **EXISTS** (base table) |
| `oc_pollination.interactions` | **MISSING** |
| `oc_mycorrhiza.associations` | **MISSING** |
| `oc_env.climate_summaries` | **MISSING** |

Taxonomy backbone confirmed present: `oc_graph.kg_nodes`, `oc_graph.kg_edges` (base tables).

### 2.4 Can the required contract columns be mapped from the existing tables?
Column probe of the five existing tables against the `source_pk` + `taxon_pk` contract:

| Table | PK column | Taxon-link column | Mapping status |
|---|---|---|---|
| `oc_atlas.occurrences` | `occurrence_id` | `taxon_id` ✓ | Direct mapping possible; SQL not written |
| `oc_conservation.conservation_records` | `conservation_id` | `taxon_id` ✓ | Direct mapping possible; SQL not written |
| `oc_core.media_assets` | `media_id` | `taxon_id` ✓ | Direct mapping possible; SQL not written |
| `oc_traits.traits` | `trait_id` | **none** (7 cols, no taxon linkage) | Needs a join/resolved view (`domain_sources` suggests `oc_views.trait_resolved_v4`) |
| `oc_citations.literature_nodes` | `literature_node_id` | **none** | Needs join to `oc_citations.canonical_taxon_literature_edges` |

---

## 3. Per-domain status table

| Domain | Adapter source table | Prod table exists? | Taxon link | Records read (dry run) | Nodes | Edges | Connection status |
|---|---|---|---|---|---|---|---|
| Geographic Occurrences | `oc_atlas.occurrences` | ✓ | `taxon_id` | 0 | 0 | 0 | **Awaiting SQL** (mapping trivial) |
| Traits | `oc_traits.traits` | ✓ | none | 0 | 0 | 0 | **Awaiting mapping** (join to resolved view) |
| Pollinators | `oc_pollination.interactions` | ✗ | — | 0 | 0 | 0 | **Placeholder** (source table missing) |
| Mycorrhizae | `oc_mycorrhiza.associations` | ✗ | — | 0 | 0 | 0 | **Placeholder** (source table missing) |
| Conservation | `oc_conservation.conservation_records` | ✓ | `taxon_id` | 0 | 0 | 0 | **Awaiting SQL** (mapping trivial) |
| Climate | `oc_env.climate_summaries` | ✗ | — | 0 | 0 | 0 | **Placeholder** (source table missing) |
| Literature | `oc_citations.literature_nodes` | ✓ | none | 0 | 0 | 0 | **Awaiting mapping** (join to taxon-literature edges) |
| Images / Phenotype | `oc_core.media_assets` | ✓ | `taxon_id` | 0 | 0 | 0 | **Awaiting SQL** (mapping trivial) |

**No domain is FULLY CONNECTED.** None reads real data end-to-end because no
projection SQL is registered.

Per-domain SQL executed against production: **none** (no live provider is wired).
Provenance coverage, quality scores, missing-identifier counts, and validation
warnings are all **not measurable on real data** because zero real rows flow.
On fixtures, provenance is retained on every spec (`source_table`, `source_pk`,
`rule_name=<domain>_build`) and adapters never emit `taxon` nodes.

---

## 4. Graph-growth verification

| Domain | Source records | Nodes created | Edges created | Skipped | Warnings | Est. production growth |
|---|---|---|---|---|---|---|
| Occurrences | 0 | 0 | 0 | 0 | no source rows | 0 |
| Traits | 0 | 0 | 0 | 0 | no source rows | 0 |
| Pollinators | 0 | 0 | 0 | 0 | no source rows | 0 |
| Mycorrhizae | 0 | 0 | 0 | 0 | no source rows | 0 |
| Conservation | 0 | 0 | 0 | 0 | no source rows | 0 |
| Climate | 0 | 0 | 0 | 0 | no source rows | 0 |
| Literature | 0 | 0 | 0 | 0 | no source rows | 0 |
| Images/Phenotype | 0 | 0 | 0 | 0 | no source rows | 0 |
| **TOTALS** | **0** | **0** | **0** | **0** | 8 domains empty | **0** |

Estimated production graph growth from a dry run today: **0 nodes, 0 edges.**

---

## 5. Validation verification

`validate_graph` runs and reports correctly. On real data it cannot report
anything because no rows flow. On a taxonomy-seeded staging graph with no domain
rows, it reports the taxonomy nodes as orphans (expected — no domain edges yet),
which is why an empty dry run returns `healthy=False`. With fixture rows,
validation passes cleanly (no orphan edges, no duplicates, no endpoint failures,
no vocabulary violations, no identifier problems). The validation machinery is
functional; there is simply no production data to validate.

---

## 6. Remaining work (to reach READY)

1. **Write per-domain read-only projection SQL** and register it in a
   `queries` dict for `PostgresSourceProvider` (aliasing `source_pk`, `taxon_pk`,
   and each adapter's field columns). None exists today — this is the blocking item.
2. **Resolve the three missing source tables** — pollinators, mycorrhiza, climate.
   Locate the real production sources (candidates in `domain_sources.py`:
   `oc_globi.*`/`oc_interactions.*`, `oc_dependency.fungal_dependency_evidence`,
   `oc_env_intel.*`) and update the adapters' `source_table` + queries accordingly.
3. **Add join-based mapping** for traits and literature, which have no direct
   taxon column (traits → a resolved trait view; literature → canonical
   taxon-literature edge table).
4. **Verify controlled vocabulary** covers every emitted node/edge type against
   the vocabulary module before publish.
5. **Re-run AUDIT + DRY_RUN with the live read-only provider** to produce real
   per-domain record counts, provenance coverage, and quality distributions.
6. Only then consider an owner-authorized PUBLISH (writable repo +
   `authorized_to_publish=True`).

---

## 7. Evidence summary

- Orchestrator control logic: **verified working and safe** (AUDIT/DRY_RUN no
  writes; PUBLISH/RESUME gated; checkpoints + batching confirmed).
- Data connection: **not implemented** — no `PostgresSourceProvider` queries
  registered anywhere; 3/8 adapter source tables missing in production; 2/8 need
  join-based taxon mapping; 3/8 are directly mappable but have no SQL.
- Real graph growth achievable today: **zero.**

**Verdict: NOT READY for production population.** The infrastructure is ready;
the data-connection layer is not.
