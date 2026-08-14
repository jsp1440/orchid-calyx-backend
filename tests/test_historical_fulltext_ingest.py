from __future__ import annotations

from app.calyx_conversation.historical_fulltext_ingest import (
    documents_from_bhl_item_metadata,
)
import runtime.literature_harvester as literature


def test_bhl_ocr_pages_rank_query_matches_first() -> None:
    item = {
        "ItemID": 42,
        "Title": "Darwin on orchids",
        "ItemUrl": "https://www.biodiversitylibrary.org/item/42",
        "Rights": "Public domain",
        "Pages": [
            {
                "PageID": 1,
                "PageNumber": "1",
                "OcrText": "Preface and contents. " * 20,
            },
            {
                "PageID": 2,
                "PageNumber": "212",
                "PageUrl": "https://www.biodiversitylibrary.org/page/2",
                "OcrText": (
                    "Orchid pollination by insects and the fertilisation mechanism "
                    "of the flower are discussed here. " * 10
                ),
            },
        ],
    }

    documents = documents_from_bhl_item_metadata(
        item, query="orchid pollination fertilisation", max_pages=1
    )

    assert len(documents) == 1
    document = documents[0]
    assert document.metadata["bhl_page_id"] == "2"
    assert document.document_class == "HISTORICAL_BOTANICAL_FULLTEXT"
    assert document.representation_type == "VERBATIM"
    assert document.display_policy == "LIMITED_PREVIEW_ONLY"
    assert document.metadata["automatic_publication"] is False
    assert document.metadata["knowledge_graph_mutation"] is False


def test_bhl_ocr_rejects_short_or_missing_text() -> None:
    item = {
        "ItemID": 42,
        "Pages": [
            {"PageID": 1, "OcrText": "too short"},
            {"PageID": 2},
        ],
    }
    assert documents_from_bhl_item_metadata(item, query="orchid", max_pages=2) == []


def test_bhl_fulltext_lane_is_bounded(monkeypatch) -> None:
    monkeypatch.setenv("BHL_API_KEY", "test-key")

    class FakeClient:
        def __init__(self, *, api_key: str):
            assert api_key == "test-key"

        def page_search(self, *, search_term: str, page: int):
            assert page == 1
            return {
                "Result": [
                    {"PageID": 10, "Title": "Darwin orchids"},
                    {"PageID": 11, "Title": "Darwin orchids"},
                    {"PageID": 12, "Title": "Darwin orchids"},
                ]
            }

        def page_metadata(self, page_id: int):
            return {
                "Result": {
                    "PageID": page_id,
                    "ItemID": 7,
                    "PageNumber": str(page_id),
                    "OcrText": "orchid pollination fertilisation mechanism " * 10,
                }
            }

    calls: list[int] = []

    def fake_ingest(item, *, query: str, max_pages: int):
        calls.append(int(item["Pages"][0]["PageID"]))
        return {"status": "indexed_for_research", "indexed": 1}

    monkeypatch.setattr(literature, "BHLClient", FakeClient)
    monkeypatch.setattr(literature, "ingest_bhl_item_fulltext_for_research", fake_ingest)

    result = literature._harvest_bhl_fulltext_once(bucket=0, limit=10)

    assert calls == [10, 11]
    assert result["hydrated"] == 2
    assert result["indexed"] == 2
    assert result["automatic_publication"] is False


def test_bhl_fulltext_lane_not_due(monkeypatch) -> None:
    monkeypatch.setenv("BHL_API_KEY", "test-key")
    result = literature._harvest_bhl_fulltext_once(bucket=1, limit=5)
    assert result["status"] == "not_due"
    assert result["indexed"] == 0
