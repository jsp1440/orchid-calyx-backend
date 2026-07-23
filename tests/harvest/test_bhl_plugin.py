from unittest.mock import Mock

import pytest
import requests

from app.harvest.plugins.bhl.client import BHLClient
from app.harvest.plugins.bhl.plugin import BHLHarvester


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
    return BHLHarvester(
        persistence=DummyPersistence(), checkpoints=DummyCheckpoints(), metrics=DummyMetrics()
    )


def test_fetch_page_preserves_checkpoint(harvester):
    harvester.client = Mock()
    harvester.client.item_search.return_value = {
        "Status": "ok",
        "Result": [{"ItemID": 1}, {"ItemID": 2}],
    }
    page = harvester.fetch_page({"page": 1, "entity": "item", "search_term": "Orchidaceae"})
    assert len(page.records) == 2
    assert page.end_of_stream is False
    assert page.next_checkpoint["page"] == 2
    assert page.next_checkpoint["processed"] == 2


def test_fetch_page_rejects_unknown_result_shape(harvester):
    harvester.client = Mock()
    harvester.client.item_search.return_value = {"Status": "ok", "Result": "invalid"}
    with pytest.raises(ValueError, match="list or object"):
        harvester.fetch_page({"entity": "item", "search_term": "Orchidaceae"})


def test_normalize_item_preserves_bibliography_and_media(harvester):
    record = {
        "_bhl_entity": "item",
        "ItemID": 42,
        "Title": "The Orchidaceae of Peru",
        "Authors": [{"Name": "A. Botanist"}],
        "PublicationDetails": "London: Botanical Press, 1901",
        "Year": "1901",
        "Volume": "2",
        "ItemUrl": "https://www.biodiversitylibrary.org/item/42",
        "PdfUrl": "https://example.org/item-42.pdf",
        "Identifiers": [{"IdentifierName": "DOI", "IdentifierValue": "10.1234/orchid.42"}],
        "LicenseUrl": "https://creativecommons.org/publicdomain/mark/1.0/",
    }
    normalized = harvester.normalize(record)
    assert normalized["source_record_id"] == "42"
    assert normalized["object_type"] == "item"
    assert normalized["authors"] == ("A. Botanist",)
    assert normalized["year"] == 1901
    assert normalized["doi"] == "10.1234/orchid.42"
    assert normalized["media"][0]["media_type"] == "pdf"
    assert harvester.validate(normalized) is True


def test_normalize_page_preserves_ocr_and_plate(harvester):
    record = {
        "_bhl_entity": "page",
        "PageID": 99,
        "PageNumber": "pl. 12",
        "PageUrl": "https://www.biodiversitylibrary.org/page/99",
        "FullImageUrl": "https://example.org/page-99.jpg",
        "ThumbnailUrl": "https://example.org/page-99-thumb.jpg",
        "OcrText": "Orchis mascula",
        "Rights": "Public domain",
    }
    normalized = harvester.normalize(record)
    assert normalized["source_record_id"] == "99"
    assert normalized["page_numbers"] == ("pl. 12",)
    assert normalized["ocr_text"] == "Orchis mascula"
    assert normalized["media"][0]["media_type"] == "plate"


def test_missing_identifier_is_rejected(harvester):
    with pytest.raises(ValueError, match="stable identifier"):
        harvester.normalize({"_bhl_entity": "item", "Title": "Untitled"})


def test_client_builds_request_without_live_network():
    response = Mock(status_code=200)
    response.json.return_value = {"Status": "ok", "Result": []}
    response.raise_for_status.return_value = None
    session = Mock()
    session.get.return_value = response
    client = BHLClient(api_key="test-key", session=session, max_attempts=1, min_interval_seconds=0)
    payload = client.item_search(search_term="Orchidaceae", page=2)
    assert payload["Result"] == []
    _, kwargs = session.get.call_args
    assert kwargs["params"]["op"] == "ItemSearch"
    assert kwargs["params"]["searchterm"] == "Orchidaceae"
    assert kwargs["params"]["page"] == 2
    assert kwargs["params"]["apikey"] == "test-key"


def test_client_builds_page_metadata_request():
    response = Mock(status_code=200)
    response.json.return_value = {"Status": "ok", "Result": {"PageID": 123}}
    response.raise_for_status.return_value = None
    session = Mock()
    session.get.return_value = response
    client = BHLClient(api_key="test-key", session=session, max_attempts=1, min_interval_seconds=0)
    payload = client.page_metadata(123)
    assert payload["Result"]["PageID"] == 123
    _, kwargs = session.get.call_args
    assert kwargs["params"]["op"] == "GetPageMetadata"
    assert kwargs["params"]["pageid"] == 123
    assert kwargs["params"]["ocr"] == "t"
    assert kwargs["params"]["names"] == "t"


def test_client_validates_arguments():
    client = BHLClient(api_key="test-key", session=Mock(), min_interval_seconds=0)
    with pytest.raises(ValueError, match="search_term"):
        client.item_search(search_term="   ")
    with pytest.raises(ValueError, match="page must"):
        client.item_search(search_term="Orchidaceae", page=0)
    with pytest.raises(ValueError, match="positive integer"):
        client.page_metadata(0)


def test_client_rejects_missing_result():
    response = Mock(status_code=200)
    response.json.return_value = {"Status": "ok"}
    response.raise_for_status.return_value = None
    session = Mock()
    session.get.return_value = response
    client = BHLClient(api_key="test-key", session=session, max_attempts=1, min_interval_seconds=0)
    with pytest.raises(ValueError, match="missing Result"):
        client.item_search(search_term="Orchidaceae")


def test_client_retries_transient_failure(monkeypatch):
    failure = Mock(status_code=500)
    failure.raise_for_status.side_effect = requests.HTTPError("server error")
    success = Mock(status_code=200)
    success.raise_for_status.return_value = None
    success.json.return_value = {"Status": "ok", "Result": []}
    session = Mock()
    session.get.side_effect = [failure, success]
    monkeypatch.setattr("app.harvest.plugins.bhl.client.time.sleep", lambda _: None)
    monkeypatch.setattr("app.harvest.plugins.bhl.client.random.uniform", lambda *_: 0)
    client = BHLClient(
        api_key="test-key", session=session, max_attempts=2, backoff_seconds=0, min_interval_seconds=0
    )
    assert client.item_search(search_term="Orchidaceae")["Result"] == []
    assert session.get.call_count == 2
