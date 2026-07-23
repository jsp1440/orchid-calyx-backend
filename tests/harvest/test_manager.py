from __future__ import annotations

from typing import Any, Mapping

from app.harvest.base import BaseHarvester
from app.harvest.checkpoints import InMemoryCheckpointStore
from app.harvest.manager import HarvestManager
from app.harvest.metrics import HarvestMetrics
from app.harvest.models import HarvestPage
from app.harvest.persistence import InMemoryHarvestPersistence
from app.harvest.registry import HarvesterRegistry


class FakeHarvester(BaseHarvester):
    source = "fake"

    def fetch_page(self, checkpoint: Mapping[str, Any] | None = None) -> HarvestPage:
        offset = int((checkpoint or {}).get("offset", 0))
        if offset == 0:
            return HarvestPage(
                records=(
                    {"key": "1", "scientific_name": "Orchis testii"},
                    {"key": "2", "scientific_name": "Orchis secunda"},
                ),
                next_checkpoint={"offset": 2},
                end_of_stream=False,
            )
        return HarvestPage(records=(), next_checkpoint={"offset": 2}, end_of_stream=True)

    def normalize(self, record: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "source": self.source,
            "source_record_id": str(record["key"]),
            "scientific_name": record["scientific_name"],
        }

    def validate(self, record: Mapping[str, Any]) -> bool:
        return bool(record.get("source_record_id") and record.get("scientific_name"))


def test_manager_runs_to_completion_and_checkpoints() -> None:
    registry = HarvesterRegistry()
    registry.register(FakeHarvester)
    persistence = InMemoryHarvestPersistence()
    checkpoints = InMemoryCheckpointStore()
    metrics = HarvestMetrics()

    result = HarvestManager(
        persistence=persistence,
        checkpoints=checkpoints,
        metrics=metrics,
        plugin_registry=registry,
    ).run("fake", job_key="test")

    assert result.completed is True
    assert result.pages == 2
    assert result.fetched == 2
    assert result.persisted == 2
    assert len(persistence.all("fake")) == 2
    assert result.checkpoint.completed is True
