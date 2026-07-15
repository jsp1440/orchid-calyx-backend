# BUILD-066 — Operator Guide: Full Graph Population

Extends the BUILD-065 controlled-population guide. All commands are read-only or
staging unless `authorized_to_publish=True` is explicitly set.

## Execution modes
| Mode | Writes to prod? | Purpose |
|---|---|---|
| `AUDIT` | No | Source availability only, no graph built. |
| `DRY_RUN` | No | Full projection into an in-memory staging graph. |
| `LIMITED_POPULATION` | No | Staging, restricted to an activation allowlist. |
| `PUBLISH` | **Yes** (only if authorized) | Full write to `oc_graph`. |
| `RESUME` | **Yes** (only if authorized) | Continue a PUBLISH, skipping checkpointed domains. |

`PUBLISH`/`RESUME` are refused unless the orchestrator is constructed with
`authorized_to_publish=True`; otherwise they no-op with a warning.

## 1. Full DRY_RUN + reports (safe, default)
```python
from runtime.knowledge_graph import (
    BuildOrchestrator, ExecutionMode, PostgresGraphRepository,
    PostgresSourceProvider, InMemoryCheckpointStore, registry_by_domain,
    domain_coverage_report, graph_completeness_report, review_queues,
)
repo = PostgresGraphRepository(DSN)
src  = PostgresSourceProvider.from_registry(DSN)
orch = BuildOrchestrator(repo, src, checkpoint_store=InMemoryCheckpointStore())
report = orch.run(ExecutionMode.DRY_RUN)          # no prod writes
coverage     = domain_coverage_report(report["per_domain"], registry_by_domain())
completeness = graph_completeness_report(orch.last_target_repo)
```
Review the reports (this folder) before any publish.

## 2. Authorized full PUBLISH (only after sign-off)
```python
orch = BuildOrchestrator(repo, src, checkpoint_store=JsonFileCheckpointStore(path),
                         authorized_to_publish=True)
orch.run(ExecutionMode.PUBLISH)
```
- **Idempotent**: re-running writes nothing new (edges dedup on identity).
- Per-domain checkpoints are saved as each domain completes.

## 3. Resume after interruption
```python
orch.run(ExecutionMode.RESUME)   # skips domains already in the checkpoint store
```

## 4. Selective publish (recommended for first prod write)
Withhold the climate proxy and any name-join domain pending crosswalk by using
`LIMITED_POPULATION` with an activation allowlist, or publish domain-by-domain.
See decision-critical findings in `00-COMPLETION-REPORT.md`.

## Notes
- Staging seeds only `taxon`/`genus` nodes via `taxonomy_nodes()`; it never
  streams the full production graph and never writes to it.
- `last_target_repo` exposes the produced graph (staging or prod) for reporting.
