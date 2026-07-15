# BUILD-062 — Operator Guide: Connecting & Populating the Scientific Graph

Audience: an operator authorizing a controlled production population of the
scientific knowledge graph. This describes how source connection works, how to
inspect it read-only, and what to decide before publishing.

## 1. Where source SQL lives

All per-domain read-only projection SQL lives in **one** file:
`runtime/knowledge_graph/source_registry.py`. There is no SQL anywhere else in
the pipeline. To change how a domain reads production data, edit its
`SourceQuery` entry there.

Each `SourceQuery` declares: `domain`, `expected_tables`, `taxon_mapping`
(`direct` / `resolved_view` / `name_join`), the contract columns
(`source_pk`, `taxon_pk`), optional value / provenance / quality columns, and
the SELECT SQL. Set `enabled=False` with a `blocked_reason` to take a domain out
of the run without deleting its config.

## 2. Safety guarantees

- Every registered query is validated by `assert_safe_sql`: SELECT/WITH only,
  single statement, no forbidden keywords, comments stripped.
- `PostgresSourceProvider` re-validates on construction and before each fetch.
- The build orchestrator only writes in `PUBLISH`/`RESUME` **and** only when
  `authorized_to_publish=True`. AUDIT and DRY_RUN never write.

## 3. Read-only inspection (safe to run any time)

```python
import os
from runtime.knowledge_graph import (
    BuildOrchestrator, ExecutionMode,
    PostgresGraphRepository, PostgresSourceProvider, InMemoryCheckpointStore,
)
dsn = os.environ["DATABASE_URL"]
repo = PostgresGraphRepository(dsn)
src  = PostgresSourceProvider.from_registry(dsn)   # built from the registry

# AUDIT: per-domain row availability, no reads of full data
print(BuildOrchestrator(repo, src).run(ExecutionMode.AUDIT)["preflight"])

# DRY_RUN: full projection into a staging graph, still zero production writes
dry = BuildOrchestrator(repo, src, checkpoint_store=InMemoryCheckpointStore(),
                        batch_size=500).run(ExecutionMode.DRY_RUN)
print(dry["totals"], dry["build"]["wrote_to_production"])  # -> ..., False
```

## 4. Reading DRY_RUN output

- `per_domain[].rows_processed / nodes_written / edges_written / invalid` —
  per-domain projection counts (in staging).
- `cross_domain_validation` — `identifier_integrity`, `duplicate_relationships`,
  `orphan_edges`, `vocabulary_compliance`, `provenance_completeness`.
  **`orphan_nodes` counts backbone taxa with no domain edge yet — expected
  coverage sparsity, not a data error.** Judge data health by the edge/identity/
  provenance checks, which should all be zero/compliant.

## 5. Per-domain decisions before controlled population

| Domain | Decide before publishing |
| --- | --- |
| occurrences, conservation | Accept very low production volume (26 / 2 rows). |
| traits | Accept ~43% taxa coverage from the consensus view. |
| media | Confirm gallery view is authoritative (media_assets.taxon_id is NULL). |
| climate | **Proxy, not bioclim.** Decide whether the occurrence-derived proxy is acceptable, or wait for a real bioclim derivation. |
| pollinators, mycorrhiza, literature | **Name-join** domains — no verified taxon-id crosswalk. Accept name-collision fan-out (e.g. mycorrhiza 462→626) or build a crosswalk first. |

## 6. Authorizing a controlled population (not done in BUILD-062)

Only after per-domain sign-off:

1. Run one final DRY_RUN and confirm `wrote_to_production: False` plus clean
   identity/edge/provenance validation.
2. Publication requires explicit `authorized_to_publish=True` on the
   orchestrator **and** running `ExecutionMode.PUBLISH`. Until both are set, no
   writes occur. Prefer publishing one domain at a time and re-validating.
3. Publication is idempotent (existing nodes/edges are skipped by canonical key),
   so a re-run after a partial population is safe.

BUILD-062 deliberately stops at DRY_RUN. See the main report for the readiness
determination: **NOT READY FOR CONTROLLED PRODUCTION POPULATION.**
