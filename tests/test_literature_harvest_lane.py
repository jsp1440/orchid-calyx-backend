from __future__ import annotations

import adaptive_harvest_worker as worker
import runtime.literature_harvester as literature


def test_topic_rotation_is_deterministic() -> None:
    first = literature._topic_for_time(0)
    second = literature._topic_for_time(900)
    assert first == literature.LITERATURE_TOPICS[0]
    assert second == literature.LITERATURE_TOPICS[1]


def test_literature_runs_before_biodiversity(monkeypatch) -> None:
    order: list[str] = []

    def fake_literature(*, limit: int):
        order.append("literature")
        return {
            "status": "indexed_for_research",
            "topic": "plant_genetics_genomics",
            "discovered": 3,
            "indexed": 2,
        }

    def fake_harvester(source: str, *, limit: int):
        order.append(source)
        return {"records_examined": 1, "inserted": 1}

    monkeypatch.setattr(worker, "harvest_literature_once", fake_literature)
    monkeypatch.setattr(worker, "run_harvester", fake_harvester)

    result = worker.run_once(limit=10)

    assert order == ["literature", "inaturalist"]
    assert result["literature"]["status"] == "completed"
    assert result["biodiversity"]["selected_source"] == "inaturalist"


def test_literature_failure_does_not_block_biodiversity(monkeypatch) -> None:
    def failed_literature(*, limit: int):
        raise RuntimeError("temporary provider failure")

    def fake_harvester(source: str, *, limit: int):
        return {"records_examined": 1, "inserted": 0}

    monkeypatch.setattr(worker, "harvest_literature_once", failed_literature)
    monkeypatch.setattr(worker, "run_harvester", fake_harvester)

    result = worker.run_once(limit=10)

    assert result["literature"]["status"] == "failed"
    assert result["biodiversity"]["status"] == "worked"


def test_biodiversity_falls_through_when_source_is_idle(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        worker,
        "harvest_literature_once",
        lambda *, limit: {"status": "already_indexed", "topic": "x", "discovered": 1, "indexed": 0},
    )

    def fake_harvester(source: str, *, limit: int):
        calls.append(source)
        if source == "inaturalist":
            return {"records_examined": 0, "inserted": 0}
        return {"records_examined": 2, "inserted": 1}

    monkeypatch.setattr(worker, "run_harvester", fake_harvester)
    result = worker.run_once(limit=10)

    assert calls == ["inaturalist", "gbif"]
    assert result["biodiversity"]["selected_source"] == "gbif"
