from app.calyx_conversation.provider import DeterministicGovernedReplyProvider


def _context(results):
    return {
        "casual": False,
        "retrieval": {"results": [], "total_eligible_results": 0},
        "mission": None,
        "mission_error": None,
        "knowledge_graph": {"status": "not_requested", "taxa": []},
        "graph_literature": {"status": "not_requested", "results": []},
        "occurrence_constraints": {
            "status": "available",
            "filter": {
                "country": "Ecuador",
                "elevation_mode": "above",
                "elevation_min_m": 3000.0,
                "elevation_max_m": None,
                "target_elevation_m": None,
            },
            "results": results,
        },
    }


def test_deterministic_provider_surfaces_structured_occurrence_results():
    provider = DeterministicGovernedReplyProvider()
    reply = provider.generate(
        messages=[{"role": "user", "content": "List orchids in Ecuador above 3000 meters"}],
        governed_context=_context([
            {
                "taxonomy_id": 17,
                "scientific_name": "Example orchid",
                "kg_node_id": 42,
                "occurrence_count": 6,
                "observed_min_elevation_m": 3010.0,
                "observed_max_elevation_m": 3550.0,
            }
        ]),
    )
    assert reply.model == "calyx-governed-summary-v4-occurrence"
    assert "Example orchid" in reply.text
    assert "records=6" in reply.text
    assert "Ecuador above 3000 m" in reply.text
    assert "observational evidence" in reply.text


def test_deterministic_provider_reports_zero_result_without_inference():
    provider = DeterministicGovernedReplyProvider()
    reply = provider.generate(
        messages=[{"role": "user", "content": "List orchids in Ecuador above 10000 meters"}],
        governed_context=_context([]),
    )
    assert "no taxon records" in reply.text
    assert "zero result" in reply.text
