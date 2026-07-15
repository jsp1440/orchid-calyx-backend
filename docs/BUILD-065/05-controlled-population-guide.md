# BUILD-065 — Controlled Population Guide

## Principle
Do not activate every domain. Activate only scientifically defensible domains,
in batches, checkpointed, idempotent and reversible. No production writes occur
until an owner explicitly authorizes PUBLISH.

## Activation allowlist (Part 5)
| Activated | Withheld (reason) |
| --- | --- |
| media | climate — occurrence-derived proxy; real climate tables empty |
| traits | conservation — CITES/IUCN tables empty |
| pollinators | mycorrhiza — high name-collision/orphan rate |
| occurrences | literature — records lack verified taxon ids |

## Running controlled activation (staging, never production)
```python
from runtime.knowledge_graph import (
    BuildOrchestrator, ExecutionMode, ACTIVATED_DOMAINS,
    PostgresGraphRepository, PostgresSourceProvider, InMemoryCheckpointStore)
orch = BuildOrchestrator(
    PostgresGraphRepository(dsn), PostgresSourceProvider.from_registry(dsn),
    checkpoint_store=InMemoryCheckpointStore(), batch_size=500,
    activated_domains=ACTIVATED_DOMAINS)
report = orch.run(ExecutionMode.LIMITED_POPULATION)   # wrote_to_production == False
```
Under `LIMITED_POPULATION` the withheld domains report `status="skipped"
(withheld)` and the production graph is never touched.

## Enabling real publication (owner-gated)
Only after owner approval: switch to `ExecutionMode.PUBLISH` with
`authorized_to_publish=True`. Publication is idempotent (canonical-key skip) and
resumable (`ExecutionMode.RESUME` from the checkpoint store). Prefer one domain
at a time.
