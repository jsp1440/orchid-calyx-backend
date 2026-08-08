from __future__ import annotations

from typing import ClassVar

from app.evidence_retrieval.engine import RetrievalEngine
from app.evidence_retrieval.models import RetrievalQuery
from runtime.continuum_conversation import ContinuumConversationService


class FixtureProvider:
    metadata: ClassVar[dict[str, str]] = {"provider": "fixture"}

    def embed_batch(self, values):
        return [[1.0, 0.0] for _ in values]


class FixtureRepo:
    documents: ClassVar[list[dict]] = [
        {
            "index_document_id": "index-target",
            "source_object_type": "CLAIM",
            "revision_id": "rev-target",
            "parent_id": "parent-target",
            "active": True,
            "content_hash": "hash-target",
            "anchors": [],
            "metadata": {
                "source_document_id": "document-target",
                "display_policy": "FULL_TEXT_ALLOWED",
                "document_title": "Target paper",
            },
        },
        {
            "index_document_id": "index-other",
            "source_object_type": "CLAIM",
            "revision_id": "rev-other",
            "parent_id": "parent-other",
            "active": True,
            "content_hash": "hash-other",
            "anchors": [],
            "metadata": {
                "source_document_id": "document-other",
                "display_policy": "FULL_TEXT_ALLOWED",
                "document_title": "Other paper",
            },
        },
    ]
    lexical: ClassVar[list[dict]] = [
        {
            "index_document_id": "index-target",
            "normalized_text": "flowering evidence from the target document",
            "title": "Target paper",
        },
        {
            "index_document_id": "index-other",
            "normalized_text": "flowering evidence from another document",
            "title": "Other paper",
        },
    ]
    vectors: ClassVar[list[dict]] = [
        {"index_document_id": "index-target", "vector": [1.0, 0.0], "active": True},
        {"index_document_id": "index-other", "vector": [1.0, 0.0], "active": True},
    ]


class CapturingRetrieval:
    def __init__(self):
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return {
            "retrieval_mode": query.mode,
            "ranking_configuration_version": "fixture",
            "total_candidates": 0,
            "total_eligible_results": 0,
            "elapsed_ms": 0.1,
            "results": [],
        }


def test_retrieval_document_scope_excludes_other_documents():
    engine = RetrievalEngine(FixtureRepo(), FixtureProvider())
    result = engine.search(
        RetrievalQuery(
            text="flowering",
            mode="HYBRID",
            filters={"document_id": "document-target"},
            internal_access=True,
        )
    )

    assert len(result["results"]) == 1
    assert result["results"][0]["citation"]["revision_id"] == "rev-target"
    assert result["results"][0]["citation"]["document_title"] == "Target paper"
    assert result["excluded_counts"]["DOCUMENT_SCOPE"] == 1
    assert result["applied_filters"]["filters"] == {"document_id": "document-target"}


def test_document_scope_can_match_revision_or_parent_identity():
    engine = RetrievalEngine(FixtureRepo(), FixtureProvider())

    by_revision = engine.search(RetrievalQuery(text="flowering", filters={"document_id": "rev-target"}))
    by_parent = engine.search(
        RetrievalQuery(text="flowering", filters={"document_id": "parent-target"})
    )

    assert [item["citation"]["revision_id"] for item in by_revision["results"]] == ["rev-target"]
    assert [item["citation"]["revision_id"] for item in by_parent["results"]] == ["rev-target"]


def test_conversation_passes_active_document_as_exact_retrieval_filter():
    retrieval = CapturingRetrieval()
    service = ContinuumConversationService(retrieval=retrieval)

    response = service.ask(
        "What does this paper report?",
        context={"active_project_id": "project-1", "active_document_id": "document-target"},
    )

    assert retrieval.queries[0].filters == {"document_id": "document-target"}
    trace = response["tool_trace"][0]
    assert trace["document_scope"] == "document-target"
    assert trace["document_scope_applied"] is True
    assert response["context"]["active_document_id"] == "document-target"
    assert response["model_knowledge_used"] is False
    assert response["scientific_publication_authorized"] is False
    assert response["knowledge_graph_mutation_authorized"] is False


def test_conversation_without_document_scope_remains_global_retrieval():
    retrieval = CapturingRetrieval()
    service = ContinuumConversationService(retrieval=retrieval)

    response = service.ask("What evidence exists?")

    assert retrieval.queries[0].filters == {}
    assert response["tool_trace"][0]["document_scope"] is None
    assert response["tool_trace"][0]["document_scope_applied"] is False
