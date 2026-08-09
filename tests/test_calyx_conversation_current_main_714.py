from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from app.conversation_memory.report import build_conversation_markdown
from app.conversation_memory.service import ConversationMemoryService
from app.evidence_retrieval.engine import RetrievalEngine
from app.evidence_retrieval.models import RetrievalQuery
from app.routers.calyx_conversation_sources import router as source_router
from app.routers.calyx_operator_chat import router as chat_router
from runtime.continuum_conversation import ContinuumConversationService


class Repo:
    def __init__(self):
        self.documents = [
            {
                "index_document_id": "idx-collision",
                "revision_id": "doc-target",
                "parent_id": "parent-target",
                "source_object_type": "PAPER",
                "content_hash": "hash-collision",
                "active": True,
                "version": 1,
                "anchors": [],
                "metadata": {
                    "document_id": "other-doc",
                    "source_document_id": "other-doc",
                    "display_policy": "FULL_TEXT_ALLOWED",
                },
            },
            {
                "index_document_id": "idx-target",
                "revision_id": "rev-target",
                "parent_id": "parent-other",
                "source_object_type": "PAPER",
                "content_hash": "hash-target",
                "active": True,
                "version": 1,
                "anchors": [],
                "metadata": {
                    "document_id": "doc-target",
                    "source_document_id": "doc-target",
                    "display_policy": "FULL_TEXT_ALLOWED",
                    "document_title": "Target paper",
                },
            },
        ]
        self.lexical = [
            {
                "index_document_id": "idx-collision",
                "normalized_text": "orchid evidence collision",
                "title": "Collision",
                "language": "en",
            },
            {
                "index_document_id": "idx-target",
                "normalized_text": "orchid evidence target",
                "title": "Target",
                "language": "en",
            },
        ]
        self.vectors = []


class Provider:
    metadata: ClassVar[dict[str, str]] = {"provider": "fixture"}

    def embed_batch(self, values):
        return [[1.0] for _ in values]


def test_document_scope_matches_only_canonical_document_namespace():
    engine = RetrievalEngine(Repo(), Provider())
    result = engine.search(
        RetrievalQuery(
            text="orchid",
            mode="LEXICAL",
            filters={"document_id": "doc-target"},
            limit=10,
        )
    )

    assert result["total_eligible_results"] == 1
    assert result["excluded_counts"]["DOCUMENT_SCOPE"] == 1
    item = result["results"][0]
    assert item["result_id"]
    assert item["citation"]["document_id"] == "doc-target"
    assert item["citation"]["revision_id"] == "rev-target"


def test_document_scope_does_not_cross_match_revision_or_parent_ids():
    engine = RetrievalEngine(Repo(), Provider())
    for collision in ("rev-target", "parent-target"):
        result = engine.search(
            RetrievalQuery(
                text="orchid",
                mode="LEXICAL",
                filters={"document_id": collision},
                limit=10,
            )
        )
        assert result["total_eligible_results"] == 0
        assert result["excluded_counts"]["DOCUMENT_SCOPE"] == 2


class FakeRetrieval:
    def __init__(self):
        self.query = None

    def search(self, query):
        self.query = query
        return {
            "retrieval_mode": "HYBRID",
            "ranking_configuration_version": "fixture",
            "total_candidates": 1,
            "total_eligible_results": 1,
            "elapsed_ms": 1.0,
            "results": [
                {
                    "result_id": "result-1",
                    "rank": 1,
                    "fused_score": 0.9,
                    "object_type": "PAPER",
                    "title": "Evidence",
                    "authorized_excerpt": "Document-scoped orchid evidence.",
                    "citation": {
                        "document_id": "doc-target",
                        "revision_id": "rev-target",
                    },
                    "reliability_signals": {"peer_reviewed": "YES"},
                    "review_state": "REVIEWED",
                    "verification_state": "VERIFIED",
                    "temporal_status": "CURRENT",
                    "display_policy": "FULL_TEXT_ALLOWED",
                    "collections": ["literature"],
                }
            ],
        }


class FakeGraph:
    def lookup_taxon(self, taxon_id, *, depth=1, limit=50):
        return {
            "status": "found",
            "taxon_id": taxon_id,
            "canonical_key": f"taxon:{taxon_id}",
            "focal_node": {"label": "Laelia anceps"},
            "edge_types": ["HAS_OCCURRENCE"],
            "domain_coverage": {"occurrence": 1},
            "data_gaps": ["mycorrhiza"],
            "graph": {"node_count": 2, "edge_count": 1},
        }


def test_conversation_applies_exact_document_scope_and_read_only_graph():
    retrieval = FakeRetrieval()
    service = ContinuumConversationService(retrieval=retrieval, graph_tool=FakeGraph())
    result = service.ask(
        "What evidence is available?",
        context={
            "active_document_id": "doc-target",
            "active_taxon_id": "Laelia anceps",
        },
    )

    assert retrieval.query.filters == {"document_id": "doc-target"}
    assert result["epistemic_status"] == "continuum_evidence_and_graph"
    assert result["model_knowledge_used"] is False
    assert result["scientific_publication_authorized"] is False
    assert result["knowledge_graph_mutation_authorized"] is False
    assert result["tool_trace"][1]["knowledge_graph_mutation_authorized"] is False


def test_persisted_source_ref_keeps_exact_document_identity():
    source = ConversationMemoryService._source_ref(
        {
            "result_id": "result-1",
            "object_type": "PAPER",
            "title": "Evidence",
            "citation": {
                "document_id": "doc-target",
                "revision_id": "rev-target",
                "identifier": "doi:fixture",
                "locator": "p. 4",
                "document_title": "Evidence paper",
            },
        }
    )
    assert source["citation"]["document_id"] == "doc-target"
    assert source["citation"]["revision_id"] == "rev-target"


def test_report_deduplicates_source_ledger_without_evidence_upgrade():
    source = {
        "result_id": "result-1",
        "object_type": "PAPER",
        "title": "Evidence",
        "citation": {
            "document_id": "doc-target",
            "revision_id": "rev-target",
            "identifier": "doi:fixture",
            "locator": "p. 4",
        },
    }
    conversation = {
        "conversation_id": "conversation-1",
        "title": "Fixture",
        "messages": [
            {"role": "CALYX", "content": "First", "source_refs": [source]},
            {"role": "CALYX", "content": "Second", "source_refs": [source]},
        ],
    }
    report = build_conversation_markdown(conversation)
    assert report.count('<a id="source-1"></a>Source 1:') == 1
    assert "Source 2:" not in report
    assert report.count("- Sources: [Source 1](#source-1)") == 2
    assert "Evidence authority: `false`" in report
    assert "Document ID: `doc-target`" in report


def test_current_main_routes_and_migration_governance_are_present():
    chat_paths = {route.path for route in chat_router.routes}
    source_paths = {route.path for route in source_router.routes}
    assert "/brain/mission-control/chat/ask" in chat_paths
    assert "/brain/mission-control/chat/conversations" in chat_paths
    assert "/brain/mission-control/chat/conversations/{conversation_id}/report" in chat_paths
    assert (
        "/brain/mission-control/chat/conversations/{conversation_id}/sources/{result_id}/project-link"
        in source_paths
    )

    migration = Path("migrations/140_calyx_conversation_sessions.sql").read_text()
    assert "conversation_messages are append-only" in migration
    assert "CHECK (evidence_authority = FALSE)" in migration
    assert "CHECK (scientific_publication_authorized = FALSE)" in migration
    assert "CHECK (knowledge_graph_mutation_authorized = FALSE)" in migration
