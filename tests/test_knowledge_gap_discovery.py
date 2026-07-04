from runtime.knowledge_gap_discovery import KnowledgeGapDiscoveryEngine


def test_knowledge_gap_discovery_generates_payload(tmp_path):
    engine = KnowledgeGapDiscoveryEngine(output_dir=tmp_path)
    payload = engine.discover(write_cache=True)

    assert payload["build"] == "BUILD-016"
    assert payload["summary"]["domains"] >= 1
    assert "gaps" in payload


def test_knowledge_gap_domains(tmp_path):
    engine = KnowledgeGapDiscoveryEngine(output_dir=tmp_path)
    engine.discover(write_cache=True)
    domains = engine.domains()

    assert domains["build"] == "BUILD-016"
    assert domains["count"] >= 1
    assert "Taxonomy" in domains["domains"]


def test_knowledge_gap_queue(tmp_path):
    engine = KnowledgeGapDiscoveryEngine(output_dir=tmp_path)
    engine.discover(write_cache=True)
    queue = engine.research_queue(limit=5)

    assert queue["build"] == "BUILD-016"
    assert queue["queue_depth"] <= 5


def test_knowledge_gap_dashboard(tmp_path):
    engine = KnowledgeGapDiscoveryEngine(output_dir=tmp_path)
    engine.discover(write_cache=True)
    dashboard = engine.dashboard()

    assert dashboard["build"] == "BUILD-016"
    assert "summary" in dashboard
    assert "top_actions" in dashboard
