from app.calyx_conversation.provider import DeterministicGovernedReplyProvider


def test_deterministic_fallback_reports_persisted_graph_when_retrieval_empty():
    provider = DeterministicGovernedReplyProvider()
    reply = provider.generate(
        messages=[{"role": "user", "content": "Tell me about Laelia anceps"}],
        governed_context={
            "casual": False,
            "retrieval": {"results": [], "total_eligible_results": 0},
            "mission": None,
            "mission_error": None,
            "knowledge_graph": {
                "status": "available",
                "taxa": [
                    {
                        "scientific_name": "Laelia anceps",
                        "status": "found",
                        "nodes": [{"node_type": "publication"}],
                        "edges": [{"edge_type": "documented_by"}],
                        "edge_types": ["documented_by", "has_image"],
                        "domain_coverage": {"literature": 1, "media": 5},
                        "data_gaps": ["pollinators"],
                    }
                ],
            },
            "graph_literature": {"status": "available", "results": []},
        },
    )
    assert reply.model == "calyx-governed-summary-v3-graph-literature"
    assert "Persisted Knowledge Graph context was found" in reply.text
    assert "Laelia anceps" in reply.text
    assert "documented_by" in reply.text
    assert "literature:1" in reply.text
    assert "semantic evidence index did not surface" in reply.text
    assert "graph connectivity alone does not justify" in reply.text


def test_deterministic_fallback_appends_graph_context_to_empty_mission():
    provider = DeterministicGovernedReplyProvider()
    reply = provider.generate(
        messages=[{"role": "user", "content": "What is known about Laelia anceps?"}],
        governed_context={
            "casual": False,
            "retrieval": {"results": []},
            "mission": {"conclusions": [], "supporting_evidence": [], "missing_evidence": []},
            "knowledge_graph": {
                "status": "available",
                "taxa": [
                    {
                        "scientific_name": "Laelia anceps",
                        "status": "found",
                        "nodes": [],
                        "edges": [{"edge_type": "occurs_at"}],
                        "edge_types": ["occurs_at"],
                        "domain_coverage": {"occurrences": 1},
                        "data_gaps": [],
                    }
                ],
            },
            "graph_literature": {"status": "available", "results": []},
        },
    )
    assert "no evidence-grounded conclusion" in reply.text
    assert "Persisted Knowledge Graph context was found" in reply.text
    assert "occurs_at" in reply.text


def test_deterministic_fallback_surfaces_graph_literature_without_claiming_full_text():
    provider = DeterministicGovernedReplyProvider()
    reply = provider.generate(
        messages=[
            {
                "role": "user",
                "content": "What does the literature say about foliar nutrient uptake in orchids?",
            }
        ],
        governed_context={
            "casual": False,
            "retrieval": {"results": [], "total_eligible_results": 0},
            "mission": None,
            "mission_error": None,
            "knowledge_graph": {"status": "not_requested", "taxa": []},
            "graph_literature": {
                "status": "available",
                "terms": ["foliar", "nutrient", "uptake"],
                "results": [
                    {
                        "kg_node_id": 11,
                        "title": "Foliar nutrient uptake in epiphytic orchids",
                        "doi": "10.1000/example",
                        "year": 2020,
                        "associated_taxa": ["Phalaenopsis aphrodite"],
                    }
                ],
            },
        },
    )
    assert "Persisted Knowledge Graph literature matches were found" in reply.text
    assert "Foliar nutrient uptake in epiphytic orchids" in reply.text
    assert "doi=10.1000/example" in reply.text
    assert "not a substitute for inspecting the underlying paper text" in reply.text
    assert "no causal or physiological conclusion is inferred" in reply.text
