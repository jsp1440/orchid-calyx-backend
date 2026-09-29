from runtime.mission_alignment import evaluate_work_alignment


def test_known_domain_with_action_is_mission_aligned():
    result = evaluate_work_alignment(
        {
            "domain": "Scientific",
            "next_action": "Ingest literature evidence with provenance.",
        }
    )

    assert result.aligned is True
    assert "gather_and_connect_scientific_knowledge" in result.objectives
    assert result.mission_id == "oc-mission-v1"


def test_unknown_domain_is_repressed_by_mission_gate():
    result = evaluate_work_alignment(
        {
            "domain": "Unclassified",
            "next_action": "Do some unrelated work.",
        }
    )

    assert result.aligned is False
    assert result.objectives == ()
    assert "not mapped" in result.reason


def test_work_without_concrete_action_is_not_admitted():
    result = evaluate_work_alignment({"domain": "Engineering"})

    assert result.aligned is False
    assert "no concrete next action" in result.reason
