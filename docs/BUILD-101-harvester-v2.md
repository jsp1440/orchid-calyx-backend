# BUILD-101 — Harvester V2 and GBIF Plugin

This build introduces a source-agnostic harvesting framework and the first production source plugin for GBIF occurrence data.

## Components

- `BaseHarvester` plugin contract
- canonical occurrence, image, trait, page, checkpoint, batch, and result models
- resumable checkpoint store
- plugin registry
- harvest manager
- metrics collector
- persistence abstraction with in-memory implementation
- GBIF occurrence API client
- GBIF normalization, validation, media extraction, and pagination
- focused tests and GitHub Actions validation

## Running the focused tests

```bash
pytest -q tests/harvest
```

## Example

```python
from app.harvest.checkpoints import InMemoryCheckpointStore
from app.harvest.manager import HarvestManager
from app.harvest.metrics import HarvestMetrics
from app.harvest.persistence import InMemoryHarvestPersistence
from app.harvest.plugins import gbif  # registers the plugin

manager = HarvestManager(
    persistence=InMemoryHarvestPersistence(),
    checkpoints=InMemoryCheckpointStore(),
    metrics=HarvestMetrics(),
)

result = manager.run(
    "gbif",
    job_key="dendrobium",
    max_pages=1,
    initial_state={"scientific_name": "Dendrobium", "limit": 100},
)
```

The checkpoint may be reused on a later run with the same `job_key`. The in-memory adapters are intended for tests and dry runs; a database-backed persistence adapter can implement the same `save_batch` contract without changing the source plugin.
