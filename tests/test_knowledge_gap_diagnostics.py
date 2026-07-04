from runtime.knowledge_gap_diagnostics import KnowledgeGapDiagnosticsEngine


FAKE_INVENTORY = {
    "status": "connected",
    "connection": "test_inventory",
    "schemas": ["oc_taxonomy", "oc_image", "oc_literature", "oc_governance"],
    "tables": [
        {"schema": "oc_taxonomy", "table": "species"},
        {"schema": "oc_taxonomy", "table": "genus"},
        {"schema": "oc_image", "table": "image_assets"},
        {"schema": "oc_literature", "table": "citations"},
        {"schema": "oc_governance", "table": "review_queue"},
    ],
}


def test_gap_diagnostics_payload_reports_build(tmp_path):
    engine = KnowledgeGapDiagnosticsEngine(output_dir=tmp_path, inventory=FAKE_INVENTORY)
    payload = engine.diagnose(write_cache=True)

    assert payload["build"] == "BUILD-017"
    assert payload["brain"]["connection"] == "test_inventory"
    assert payload["summary"]["domains"] >= 1


def test_gap_diagnostics_uses_brain_table_matches(tmp_path):
    engine = KnowledgeGapDiagnosticsEngine(output_dir=tmp_path, inventory=FAKE_INVENTORY)
    payload = engine.diagnose(write_cache=True)
    domains = payload["domain_diagnostics"]

    assert domains["Taxonomy"]["brain_score"] > 0
    assert domains["Images"]["brain_score"] > 0


def test_gap_diagnostics_queue(tmp_path):
    engine = KnowledgeGapDiagnosticsEngine(output_dir=tmp_path, inventory=FAKE_INVENTORY)
    engine.diagnose(write_cache=True)
    queue = engine.queue(limit=5)

    assert queue["build"] == "BUILD-017"
    assert queue["queue_depth"] <= 5


def test_gap_diagnostics_dashboard(tmp_path):
    engine = KnowledgeGapDiagnosticsEngine(output_dir=tmp_path, inventory=FAKE_INVENTORY)
    engine.diagnose(write_cache=True)
    dashboard = engine.dashboard()

    assert dashboard["build"] == "BUILD-017"
    assert "brain" in dashboard
    assert "summary" in dashboard
