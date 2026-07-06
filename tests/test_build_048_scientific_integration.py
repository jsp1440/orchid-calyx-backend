from runtime.science_registry import (
    coverage_gaps,
    datasets,
    dossier_queue,
    harvester_status,
    integration_status,
    mission_definitions,
    summary,
)


def test_science_priorities_remain_science_first():
    result = summary()
    top_ids = [item["department_id"] for item in result["top_priorities"]]

    assert result["status"] == "ok"
    assert "pollination" in top_ids
    assert "mycorrhiza" in top_ids
    assert "literature" in top_ids
    assert all(item["department_id"] not in {"judging", "awards"} for item in result["top_priorities"])
    assert result["safety"]["unsupported_claims_promoted"] is False


def test_dataset_registry_is_non_destructive():
    result = datasets()

    assert result["status"] == "ok"
    assert result["dataset_count"] >= 5
    assert result["safety"]["external_fetches_performed"] is False
    assert result["safety"]["database_mutations_performed"] is False
    assert any(item["dataset_id"] == "zenodo_pollination" for item in result["datasets"])
    assert any(item["dataset_id"] == "mycorrhiza_relationships" for item in result["datasets"])


def test_coverage_gaps_generate_safe_scientific_work():
    result = coverage_gaps()

    assert result["status"] == "ok"
    assert result["gap_count"] > 0
    assert "promote_unreviewed_claim" in result["blocked_actions"]
    assert all(item["risk_level"] == "safe_audit_only" for item in result["gaps"])
    assert all(item["promoted_claims"] is False for item in result["gaps"])


def test_integration_status_exposes_next_actions():
    result = integration_status()

    assert result["status"] == "ok"
    assert result["dataset_count"] >= 5
    assert result["known_gap_count"] > 0
    assert result["safety"]["destructive_actions"] is False
    assert result["safety"]["external_mutations"] is False


def test_harvester_and_dossier_queues_are_audit_only():
    harvesters = harvester_status()
    dossiers = dossier_queue()

    assert harvesters["status"] == "ok"
    assert harvesters["destructive_actions"] is False
    assert dossiers["status"] == "ok"
    assert dossiers["promoted_claims"] is False


def test_mission_definitions_include_pollination_and_mycorrhiza():
    missions = mission_definitions()
    mission_names = {item["mission_type"] for item in missions}

    assert "audit_pollinator_coverage" in mission_names
    assert "audit_mycorrhiza_coverage" in mission_names
    assert "audit_literature_extraction_coverage" in mission_names
