from hashlib import sha256

import pytest

from app.brain_mission.routes import ExistingBrainMissionAdapter
from app.evidence_retrieval.engine import RetrievalEngine
from app.evidence_retrieval.models import RetrievalQuery
from app.semantic_index.memory_repository import MemoryIndexRepository
from app.semantic_index.models import IndexDocument
from app.semantic_index.provider import DeterministicLocalProvider
from app.semantic_index.service import SemanticIndexService


def test_brain_adapter_preserves_exact_excerpt_hash_and_anchor_locators(monkeypatch):
    repository = MemoryIndexRepository()
    provider = DeterministicLocalProvider()
    document = IndexDocument(
        source_object_type="CLAIM",
        source_object_id=41,
        revision_id=42,
        extraction_run_id=43,
        text="Laelia anceps occurs in México.",
        source_anchor_ids=(101, 102),
        internal_indexing_permission=True,
        display_policy="FULL_TEXT_ALLOWED",
        metadata={
            "document_id": "paper-41",
            "anchor_locators": {
                "101": {"page": 3, "paragraph": 1},
                "102": {"page": 3, "paragraph": 2},
            },
        },
    )
    service = SemanticIndexService(repository, provider)
    plan = service.preview([document])
    service.execute(plan["index_run_id"])
    engine = RetrievalEngine(repository, provider)
    result = engine.search(
        RetrievalQuery("Laelia México", mode="LEXICAL")
    )["results"][0]
    monkeypatch.setattr("app.brain_mission.routes.ENGINE", engine)

    evidence = ExistingBrainMissionAdapter._canonical_source(result)

    assert evidence.text == document.text
    assert evidence.metadata["source_content_hash"] == sha256(document.text.encode()).hexdigest()
    assert evidence.metadata["excerpt_content_hash"] == sha256(evidence.text.encode()).hexdigest()
    assert [anchor.locator for anchor in evidence.source_anchors] == [
        {"page": 3, "paragraph": 1},
        {"page": 3, "paragraph": 2},
    ]


def test_brain_adapter_rejects_tampered_source_and_excerpt_hashes(monkeypatch):
    repository = MemoryIndexRepository()
    provider = DeterministicLocalProvider()
    document = IndexDocument(
        source_object_type="CLAIM",
        source_object_id=1,
        revision_id=2,
        extraction_run_id=3,
        text="Exact source bytes",
        source_anchor_ids=(4,),
        internal_indexing_permission=True,
        display_policy="FULL_TEXT_ALLOWED",
        metadata={"anchor_locators": {"4": {"page": 1}}},
    )
    service = SemanticIndexService(repository, provider)
    plan = service.preview([document])
    service.execute(plan["index_run_id"])
    engine = RetrievalEngine(repository, provider)
    result = engine.search(RetrievalQuery("source", mode="LEXICAL"))["results"][0]
    monkeypatch.setattr("app.brain_mission.routes.ENGINE", engine)

    bad_source = {**result, "source_content_hash": "0" * 64}
    with pytest.raises(ValueError, match="SOURCE_CONTENT_HASH_MISMATCH"):
        ExistingBrainMissionAdapter._canonical_source(bad_source)
    bad_excerpt = {**result, "authorized_excerpt": "altered"}
    with pytest.raises(ValueError, match="EXCERPT_CONTENT_HASH_MISMATCH"):
        ExistingBrainMissionAdapter._canonical_source(bad_excerpt)
