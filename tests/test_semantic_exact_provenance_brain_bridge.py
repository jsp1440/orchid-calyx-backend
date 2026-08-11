from hashlib import sha256

from app.brain_mission.routes import ExistingBrainMissionAdapter
from app.evidence_retrieval.engine import RetrievalEngine
from app.evidence_retrieval.models import RetrievalQuery
from app.semantic_index.memory_repository import MemoryIndexRepository
from app.semantic_index.provider import DeterministicLocalProvider


def test_exact_multi_anchor_result_remains_consumable_by_brain(monkeypatch):
    repo = MemoryIndexRepository()
    provider = DeterministicLocalProvider()
    model = repo.ensure_model(provider.metadata)
    text = "orchid evidence with exact anchors"
    repo.documents.append(
        {
            "index_document_id": 1,
            "source_object_type": "PROTOCOL",
            "source_object_id": 7,
            "revision_id": 11,
            "extraction_run_id": 12,
            "parent_type": "PROTOCOL",
            "parent_id": 7,
            "anchors": (101, 102),
            "content_hash": sha256(text.encode()).hexdigest(),
            "metadata_hash": "m",
            "model_id": model,
            "configuration_hash": "c",
            "active": True,
            "version": 1,
            "metadata": {
                "display_policy": "FULL_TEXT_ALLOWED",
                "collections": ["GENERAL_BRAIN"],
                "anchor_locators": {
                    "101": {"page": 1, "paragraph": 2},
                    "102": {"page": 2, "paragraph": 1},
                },
            },
        }
    )
    repo.lexical.append(
        {
            "index_document_id": 1,
            "normalized_text": text.casefold(),
            "verbatim_text": text,
            "language": "en",
            "title": "Exact anchors",
        }
    )
    repo.vectors.append(
        {
            "index_document_id": 1,
            "vector": provider.embed_batch([text])[0],
            "active": True,
        }
    )

    result = RetrievalEngine(repo, provider).search(
        RetrievalQuery("exact anchors", mode="LEXICAL")
    )["results"][0]
    assert result["citation"]["locator"] == {
        "source_anchors": [
            {"anchor_id": 101, "locator": {"page": 1, "paragraph": 2}},
            {"anchor_id": 102, "locator": {"page": 2, "paragraph": 1}},
        ]
    }

    from app.brain_mission import routes as brain_routes

    monkeypatch.setattr(
        brain_routes.semantic_index_routes,
        "get_repository_for_read",
        lambda: repo,
    )
    evidence = ExistingBrainMissionAdapter._canonical_source(result)
    assert [anchor.anchor_id for anchor in evidence.source_anchors] == [101, 102]
    for anchor in evidence.source_anchors:
        assert anchor.locator == result["citation"]["locator"]
