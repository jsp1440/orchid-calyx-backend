# BUILD-060 — Unified Scientific Knowledge Graph Build: Operator Guide

**Repository:** jsp1440/orchid-calyx-backend
**Branch:** `feat/scientific-knowledge-graph-completion` (extends PR #56)
**Scope:** Adds a single Build Orchestrator + domain adapters on top of the
existing knowledge-graph infrastructure. **No production writes**, no migrations,
no destructive operations are performed by this change. Publishing is disabled
until an operator explicitly authorizes it.

---

## 1. What this adds

BUILD-060 completes the population system for the scientific graph. PR #56
delivered the read-only traversal API, repository abstraction, idempotent
publisher, controlled vocabulary and quality checks. BUILD-060 reuses all of
that and adds:

| Module | Responsibility |
|---|---|
| `runtime/knowledge_graph/sources.py` | `SourceProvider` protocol; `InMemorySourceProvider` (tests/dry-run) and read-only `PostgresSourceProvider` |
| `runtime/knowledge_graph/adapters.py` | 8 domain adapters (occurrences, traits, pollinators, mycorrhiza, conservation, climate, literature, images/phenotype) built from one shared factory |
| `runtime/knowledge_graph/checkpoint.py` | Per-domain `Checkpoint`; in-memory and JSON-file stores; drives Resume |
| `runtime/knowledge_graph/validation.py` | Automatic validation (identifiers, duplicates, orphans, vocabulary, provenance, quality, cross-domain) |
| `runtime/knowledge_graph/orchestrator.py` | `BuildOrchestrator` + `ExecutionMode`; the full pipeline and reporting |

Nothing here duplicates or redesigns the existing repository, publisher, quality
or vocabulary modules — the adapters and orchestrator only supply the
domain-specific row→spec mapping and the run-control logic.

---

## 2. Pipeline

1. Preflight audit (source availability per domain)
2. Geographic occurrences
3. Traits
4. Pollinators
5. Mycorrhizae
6. Conservation
7. Climate & environmental
8. Literature-derived relationships
9. Images / phenotype
10. Cross-domain validation
11. Final build report

Domains run in registry order (`DOMAIN_ADAPTERS`). A checkpoint is saved after
each domain.

---

## 3. Execution modes

| Mode | Writes to production? | What it does |
|---|---|---|
| `AUDIT` | No | Reports source-row availability per domain; runs no adapters. |
| `DRY_RUN` | No | Runs adapters into an in-memory staging graph seeded read-only with taxonomy nodes; validates; reports projected growth. |
| `PUBLISH` | Only if authorized | Publishes into the writable repository in idempotent batches, checkpointing each domain. **Disabled unless `authorized_to_publish=True`.** |
| `RESUME` | Only if authorized | Same as PUBLISH but skips domains already `completed`/`skipped` in the checkpoint store. |

`AUDIT` and `DRY_RUN` can never write to the production graph. Even in `PUBLISH`,
if `authorized_to_publish` is `False` the orchestrator performs no writes and
returns a report explaining that publishing was not authorized.

---

## 4. Running a dry run (safe, default)

```python
from runtime.knowledge_graph import (
    BuildOrchestrator, ExecutionMode,
    PostgresGraphRepository, PostgresSourceProvider,
)

# Read-only production graph repository (traversal/seed reads only).
repo = PostgresGraphRepository(dsn=DATABASE_URL)

# Operator-reviewed, read-only SELECTs per domain. Each query must expose
# `source_pk` and `taxon_pk` columns plus the fields the adapter reads.
source = PostgresSourceProvider(dsn=DATABASE_URL, queries={
    "occurrences": "SELECT id AS source_pk, taxon_id AS taxon_pk, locality, latitude, longitude FROM oc_atlas.occurrences",
    # ... one query per domain you intend to build ...
})

orch = BuildOrchestrator(repo, source, batch_size=500)
report = orch.run(ExecutionMode.DRY_RUN)   # no writes
print(report["totals"], report["estimated_graph_growth"])
```

The report includes: per-domain statistics (nodes created, edges created,
records skipped, invalid), a validation summary, estimated production graph
growth, warnings and errors.

---

## 5. Publishing (owner-authorized only)

Publishing is intentionally gated. To publish you must (a) pass a **writable**
repository and (b) set `authorized_to_publish=True`.

```python
orch = BuildOrchestrator(
    repo=writable_repo,               # writable graph repository
    source=source,
    checkpoint_store=JsonFileCheckpointStore("build_checkpoints.json"),
    batch_size=500,
    authorized_to_publish=True,       # explicit owner authorization
)
report = orch.run(ExecutionMode.PUBLISH)
```

Publishing is **idempotent**: nodes upsert on `canonical_key`
(`<node_type>:<source_pk>`) and edges upsert on
`(edge_type, from, to, source_table)`. Re-running publishes nothing new for
rows already present — `skipped_existing_*` counters increase instead.

> This change does not ship a writable production repository. Providing one, and
> setting `authorized_to_publish=True`, is a deliberate owner action taken
> outside this PR.

---

## 6. Resume

If a publish run is interrupted, re-run in `RESUME` mode with the **same**
checkpoint store. Domains already marked complete are skipped; the run continues
from the first incomplete domain. Because publishing is idempotent, resuming is
always safe even if a domain was partially published.

```python
orch = BuildOrchestrator(repo, source,
    checkpoint_store=JsonFileCheckpointStore("build_checkpoints.json"),
    authorized_to_publish=True)
orch.run(ExecutionMode.RESUME)
```

---

## 7. Validation

Every dry-run and publish ends with `validate_graph(...)`, which checks:
identifier integrity, duplicate relationships, orphan nodes, orphan (dangling)
edges, controlled-vocabulary compliance, provenance completeness, structural
quality scores, and cross-domain endpoint consistency. `total_problems == 0`
implies `healthy: true`.

---

## 8. Guarantees

- No production database writes occur in AUDIT or DRY_RUN, or in PUBLISH/RESUME
  without explicit authorization.
- No migrations are executed by this change.
- The test suite opens no database connection (in-memory repositories and source
  provider only).
- Adapters never emit `taxon` nodes, so a domain build cannot overwrite the
  taxonomy backbone's identities or labels.
