from runtime.brain_gap_diagnostics import BrainGapDiagnostics


def test_brain_gap_diagnostics_degrades_without_database():
    diagnostics = BrainGapDiagnostics(database_url=None)
    payload = diagnostics.status()

    assert payload["build"] == "BUILD-017"
    assert payload["status"] == "degraded"
    assert payload["brain_connection"] == "unavailable"


def test_brain_gap_table_matching():
    diagnostics = BrainGapDiagnostics(database_url=None)
    tables = [
        {"schema": "oc_taxonomy", "table": "species", "estimated_rows": 100},
        {"schema": "oc_image", "table": "image_assets", "estimated_rows": 200},
        {"schema": "oc_literature", "table": "citation", "estimated_rows": 50},
    ]
    matches = diagnostics._match_domain_tables(tables)

    assert len(matches["Taxonomy"]) >= 1
    assert len(matches["Images"]) >= 1
    assert len(matches["Literature"]) >= 1


def test_brain_gap_coverage_from_tables():
    diagnostics = BrainGapDiagnostics(database_url=None)
    domain_tables = {
        "Taxonomy": [{"schema": "oc_taxonomy", "table": "species", "estimated_rows": 100, "matched_keywords": ["species"]}],
        "Images": [],
    }
    coverage = diagnostics._coverage_from_tables(domain_tables)

    assert coverage["Taxonomy"]["status"] in {"partial", "connected"}
    assert coverage["Images"]["status"] == "not_connected"


def test_brain_gap_queue_degraded_mode():
    diagnostics = BrainGapDiagnostics(database_url=None)
    queue = diagnostics.queue(limit=5)

    assert queue["build"] == "BUILD-017"
    assert "queue_depth" in queue
