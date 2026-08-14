from __future__ import annotations

import adaptive_harvest_worker as worker
import runtime.literature_harvester as literature


def _no_due_interactions(*, limit: int):
    return {"status": "not_due", "provider": "Global Biotic Interactions", "indexed": 0}


def test_topic_rotation_is_deterministic() -> None:
    first = literature._topic_for_time(0)
    second = literature._topic_for_time(900)
    assert first == literature.LITERATURE_TOPICS[0]
    assert second == literature.LITERATURE_TOPICS[1]


def test_bhl_lane_reports_missing_key(monkeypatch) -> None:
    monkeypatch.delenv("BHL_API_KEY", raising=False)
    result = literature._harvest_bhl_once(bucket=0, limit=5)
    assert result["status"] == "not_configured"
    assert result["required_environment"] == "BHL_API_KEY"


def test_bhl_lane_skips_when_not_due(monkeypatch) -> None:
    monkeypatch.setenv("BHL_API_KEY", "test-key")
    result = literature._harvest_bhl_once(bucket=1, limit=5)
    assert result["status"] == "not_due"


def test_crossref_lane_skips_when_not_due(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Crossref network must not be called when lane is not due")

    monkeypatch.setattr(literature.requests, "get", fail_if_called)
    result = literature._harvest_crossref_once(bucket=1, limit=5)
    assert result["status"] == "not_due"


def test_crossref_lane_harvests_metadata_when_due(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "message": {
                    "items": [
                        {
                            "DOI": "10.1234/orchid.test",
                            "title": ["Orchid pollination test"],
                            "author": [{"given": "A", "family": "Botanist"}],
                        }
                    ]
                }
            }

    def fake_get(url, *, params, timeout, headers):
        assert url == literature.CROSSREF_WORKS_URL
        assert params["rows"] == 5
        assert "query.bibliographic" in params
        return FakeResponse()

    captured: dict[str, object] = {}

    def fake_ingest(records, *, query):
        captured["records"] = records
        captured["query"] = query
        return {"status": "indexed_for_research", "indexed": 1}

    monkeypatch.setattr(literature.requests, "get", fake_get)
    monkeypatch.setattr(literature, "ingest_crossref_works_for_research", fake_ingest)
    result = literature._harvest_crossref_once(bucket=0, limit=5)

    assert result["status"] == "indexed_for_research"
    assert result["discovered"] == 1
    assert result["indexed"] == 1
    assert captured["records"][0]["DOI"] == "10.1234/orchid.test"


def test_literature_and_interactions_run_before_biodiversity(monkeypatch) -> None:
    order: list[str] = []

    def fake_literature(*, limit: int):
        order.append("literature")
        return {
            "status": "indexed_for_research",
            "topic": "plant_genetics_genomics",
            "discovered": 3,
            "indexed": 2,
        }

    def fake_interactions(*, limit: int):
        order.append("interactions")
        return {"status": "not_due", "provider": "Global Biotic Interactions", "indexed": 0}

    def fake_harvester(source: str, *, limit: int):
        order.append(source)
        return {"records_examined": 1, "inserted": 1}

    monkeypatch.setattr(worker, "harvest_literature_once", fake_literature)
    monkeypatch.setattr(worker, "harvest_interactions_once", fake_interactions)
    monkeypatch.setattr(worker, "run_harvester", fake_harvester)

    result = worker.run_once(limit=10)

    assert order == ["literature", "interactions", "inaturalist"]
    assert result["literature"]["status"] == "completed"
    assert result["interactions"]["status"] == "completed"
    assert result["biodiversity"]["selected_source"] == "inaturalist"


def test_literature_failure_does_not_block_biodiversity(monkeypatch) -> None:
    def failed_literature(*, limit: int):
        raise RuntimeError("temporary provider failure")

    def fake_harvester(source: str, *, limit: int):
        return {"records_examined": 1, "inserted": 0}

    monkeypatch.setattr(worker, "harvest_literature_once", failed_literature)
    monkeypatch.setattr(worker, "harvest_interactions_once", _no_due_interactions)
    monkeypatch.setattr(worker, "run_harvester", fake_harvester)

    result = worker.run_once(limit=10)

    assert result["literature"]["status"] == "failed"
    assert result["biodiversity"]["status"] == "worked"


def test_interaction_failure_does_not_block_biodiversity(monkeypatch) -> None:
    monkeypatch.setattr(
        worker,
        "harvest_literature_once",
        lambda *, limit: {"status": "already_indexed", "topic": "x", "discovered": 1, "indexed": 0},
    )
    monkeypatch.setattr(
        worker,
        "harvest_interactions_once",
        lambda *, limit: (_ for _ in ()).throw(RuntimeError("temporary GloBI failure")),
    )
    monkeypatch.setattr(
        worker,
        "run_harvester",
        lambda source, *, limit: {"records_examined": 1, "inserted": 1},
    )

    result = worker.run_once(limit=10)
    assert result["interactions"]["status"] == "failed"
    assert result["biodiversity"]["status"] == "worked"


def test_biodiversity_falls_through_to_global_gbif(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        worker,
        "harvest_literature_once",
        lambda *, limit: {"status": "already_indexed", "topic": "x", "discovered": 1, "indexed": 0},
    )
    monkeypatch.setattr(worker, "harvest_interactions_once", _no_due_interactions)

    def fake_harvester(source: str, *, limit: int):
        calls.append(source)
        return {"records_examined": 0, "inserted": 0}

    def fake_global_gbif(*, max_pages: int):
        calls.append("gbif")
        return {
            "occurrences_added": 1,
            "images_added": 1,
            "records_examined": 300,
            "next_offset": 300,
            "pages": 1,
            "bulk_download_required": False,
        }

    monkeypatch.setattr(worker, "run_harvester", fake_harvester)
    monkeypatch.setattr(worker, "run_global_gbif", fake_global_gbif)
    result = worker.run_once(limit=10)

    assert calls == ["inaturalist", "gbif"]
    assert result["biodiversity"]["selected_source"] == "gbif"
    metadata = result["biodiversity"]["attempts"][-1]["result"]["source_response_metadata"]
    assert metadata["global_occurrence_stream"] is True
    assert metadata["media_filter"] is None
