from unittest.mock import Mock

import pytest
import requests

from app.harvest.plugins.inaturalist.client import INaturalistClient
from app.harvest.plugins.inaturalist.plugin import INaturalistHarvester


class DummyPersistence:
    def save_batch(self, *, source, records):
        return len(records)


class DummyCheckpoints:
    def save_from_state(self, source, job_key, state):
        self.saved = (source, job_key, state)

    def load(self, source, job_key):
        return None


class DummyMetrics:
    def snapshot(self, source):
        return {"source": source}


@pytest.fixture
def harvester():
    return INaturalistHarvester(
        persistence=DummyPersistence(), checkpoints=DummyCheckpoints(), metrics=DummyMetrics()
    )


def test_fetch_page_preserves_checkpoint(harvester):
    harvester.client = Mock()
    harvester.client.observations.return_value = {
        "total_results": 2,
        "results": [{"id": 1}, {"id": 2}],
    }
    page = harvester.fetch_page({"page": 1, "per_page": 2, "taxon_name": "Orchidaceae"})
    assert len(page.records) == 2
    assert page.end_of_stream is True
    assert page.next_checkpoint["page"] == 2
    assert page.next_checkpoint["processed"] == 2


def test_normalize_observation_and_images(harvester):
    record = {
        "id": 42,
        "taxon": {"id": 99, "name": "Cattleya maxima"},
        "location": "-12.5,-77.1",
        "place_guess": "Peru",
        "observed_on": "2025-01-02",
        "quality_grade": "research",
        "captive": False,
        "license_code": "cc-by",
        "user": {"login": "observer"},
        "photos": [{
            "id": 7,
            "url": "https://inaturalist-open-data.s3.amazonaws.com/photos/7/square.jpg",
            "license_code": "cc-by",
            "attribution": "(c) Observer, CC BY",
        }],
    }
    normalized = harvester.normalize(record)
    assert normalized["source_record_id"] == "42"
    assert normalized["scientific_name"] == "Cattleya maxima"
    assert normalized["latitude"] == -12.5
    assert normalized["longitude"] == -77.1
    assert normalized["quality_grade"] == "research"
    assert normalized["images"][0]["url"].endswith("original.jpg")
    assert normalized["images"][0]["license"] == "cc-by"


def test_missing_required_fields_are_rejected(harvester):
    with pytest.raises(ValueError, match="missing id"):
        harvester.normalize({"taxon": {"name": "Orchis mascula"}})
    with pytest.raises(ValueError, match="scientific name"):
        harvester.normalize({"id": 1})


def test_client_builds_request_without_live_network():
    response = Mock(status_code=200)
    response.json.return_value = {"results": []}
    response.raise_for_status.return_value = None
    session = Mock()
    session.get.return_value = response
    client = INaturalistClient(session=session, max_attempts=1)
    payload = client.observations(page=2, per_page=50, taxon_name="Orchidaceae", photos=True)
    assert payload == {"results": []}
    _, kwargs = session.get.call_args
    assert kwargs["params"]["page"] == 2
    assert kwargs["params"]["taxon_name"] == "Orchidaceae"
    assert kwargs["params"]["photos"] == "true"
    assert "User-Agent" in kwargs["headers"]


def test_client_retries_transient_failure(monkeypatch):
    failure = Mock(status_code=500)
    failure.raise_for_status.side_effect = requests.HTTPError("server error")
    success = Mock(status_code=200)
    success.raise_for_status.return_value = None
    success.json.return_value = {"results": []}
    session = Mock()
    session.get.side_effect = [failure, success]
    monkeypatch.setattr("app.harvest.plugins.inaturalist.client.time.sleep", lambda _: None)
    monkeypatch.setattr("app.harvest.plugins.inaturalist.client.random.uniform", lambda *_: 0)
    client = INaturalistClient(session=session, max_attempts=2, backoff_seconds=0)
    assert client.observations()["results"] == []
    assert session.get.call_count == 2
