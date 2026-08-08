from __future__ import annotations

from runtime.continuum_conversation import ContinuumConversationService
from runtime.continuum_graph_tool import ReadOnlyKnowledgeGraphTool
from runtime.knowledge_graph import Edge, InMemoryGraphRepository, Node, canonical_key


class EmptyRetrieval:
    def search(self, query):
        return {
            "retrieval_mode": query.mode,
            "ranking_configuration_version": "test-rank-v1",
            "total_candidates": 0,
            "total_eligible_results": 0,
            "elapsed_ms": 0.5,
            "results": [],
        }


class EvidenceRetrieval:
    def search(self, query):
        return {
            "retrieval_mode": query.mode,
            "ranking_configuration_version": "test-rank-v1",
            "total_candidates": 1,
            "total_eligible_results": 1,
            "elapsed_ms": 0.5,
            "results": [
                {
                    "result_id": "evidence-1",
                    "rank": 1,
                    "fused_score": 0.9,
                    "object_type": "CLAIM",
                    "title": "Ecology record",
                    "authorized_excerpt": "Recorded pollinator visitation in the focal taxon.",
                    "citation": {"revision_id": "rev-1", "locator": "p. 3"},
                    "reliability_signals": {"evidence_type": "PRIMARY"},
                    "review_state": "REVIEWED",
                    "verification_state": "VERIFIED",
                    "temporal_status": "CURRENT",
                    "display_policy": "LIMITED_PREVIEW_ONLY",
                    "collections": ["literature"],
                }
            ],
        }


def graph_tool() -> ReadOnlyKnowledgeGraphTool:
    taxon_key = canonical_key("taxon", "fixture-1")
    repo = InMemoryGraphRepository(
        nodes=[
            Node(
                kg_node_id=1,
                node_type="taxon",
                canonical_key=taxon_key,
                display_label="Dracula fixture",
                source_table="taxonomy",
                source_pk="fixture-1",
                evidence_class="canonical",
                confidence_score=1.0,
                confidence_label="high",
            ),
            Node(
                kg_node_id=2,
                node_type="pollinator",
                canonical_key="pollinator:bee-1",
                display_label="Bee fixture",
                source_table="pollinators",
                source_pk="bee-1",
                evidence_class="observed",
                confidence_score=0.9,
                confidence_label="high",
            ),
            Node(
                kg_node_id=3,
                node_type="occurrence",
                canonical_key="occurrence:occ-1",
                display_label="Occurrence fixture",
                source_table="occurrences",
                source_pk="occ-1",
                evidence_class="observed",
                confidence_score=0.8,
                confidence_label="medium",
            ),
        ],
        edges=[
            Edge(
                kg_edge_id=10,
                edge_type="POLLINATED_BY",
                from_node_id=1,
                to_node_id=2,
                source_table="pollinators",
                source_pk="edge-1",
                evidence_class="observed",
                confidence_score=0.9,
                confidence_label="high",
                rule_name="fixture",
            ),
            Edge(
                kg_edge_id=11,
                edge_type="OCCURS_AT",
                from_node_id=1,
                to_node_id=3,
                source_table="occurrences",
                source_pk="edge-2",
                evidence_class="observed",
                confidence_score=0.8,
                confidence_label="medium",
                rule_name="fixture",
            ),
        ],
    )
    return ReadOnlyKnowledgeGraphTool(repository=repo)


def test_graph_tool_returns_read_only_traversal_packet():
    result = graph_tool().lookup_taxon("fixture-1")

    assert result["status"] == "found"
    assert result["read_only"] is True
    assert result["knowledge_graph_mutation_authorized"] is False
    assert result["focal_node"]["label"] == "Dracula fixture"
    assert result["graph"]["node_count"] == 2
    assert result["graph"]["edge_count"] == 2
    assert set(result["edge_types"]) == {"OCCURS_AT", "POLLINATED_BY"}


def test_graph_tool_reports_missing_taxon_without_inventing_relationships():
    result = graph_tool().lookup_taxon("missing")

    assert result["status"] == "not_found"
    assert result["nodes"] == []
    assert result["edges"] == []
    assert result["knowledge_graph_mutation_authorized"] is False


def test_conversation_uses_graph_when_taxon_context_is_present():
    service = ContinuumConversationService(EmptyRetrieval(), graph_tool())
    result = service.ask(
        "What relationships are recorded for this taxon?",
        context={"active_taxon_id": "fixture-1"},
    )

    assert result["epistemic_status"] == "continuum_graph"
    assert result["graph_context"]["status"] == "found"
    assert "2 connected node(s) and 2 edge(s)" in result["answer"]
    assert "POLLINATED_BY" in result["answer"]
    assert result["tool_trace"][1]["tool"] == "knowledge_graph_read"
    assert result["tool_trace"][1]["read_only"] is True
    assert result["knowledge_graph_read_authorized"] is True
    assert result["knowledge_graph_mutation_authorized"] is False
    assert result["model_knowledge_used"] is False


def test_conversation_combines_evidence_and_graph_without_claiming_interpretation():
    service = ContinuumConversationService(EvidenceRetrieval(), graph_tool())
    result = service.ask(
        "What do we know about pollination and relationships?",
        context={"active_taxon_id": "fixture-1"},
    )

    assert result["epistemic_status"] == "continuum_evidence_and_graph"
    assert result["evidence_count"] == 1
    assert result["graph_context"]["graph"]["edge_count"] == 2
    assert "not a new causal or scientific interpretation" in result["answer"]
    assert result["scientific_interpretation_generated"] is False
    assert result["scientific_publication_authorized"] is False


def test_conversation_does_not_call_graph_without_taxon_context():
    class ExplodingGraph:
        def lookup_taxon(self, taxon_id, *, depth=1, limit=50):
            raise AssertionError("graph should not be called")

    result = ContinuumConversationService(EmptyRetrieval(), ExplodingGraph()).ask(
        "What evidence exists?",
        context={"active_project_id": "project-1"},
    )

    assert result["graph_context"] is None
    assert len(result["tool_trace"]) == 1
    assert result["epistemic_status"] == "unknown"
