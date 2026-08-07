from app.canonical_brain import (
    build_canonical_brain_fixture,
    build_mission_control_status,
)


def test_mission_control_status_reports_full_coverage() -> None:
    registry = build_canonical_brain_fixture()
    status = build_mission_control_status(registry)
    assert status.mode == "read-only-candidate"
    assert status.persistence_enabled is False
    assert status.publication_enabled is False
    assert status.object_count == len(registry.snapshot().objects)
    assert status.relationship_count == len(registry.snapshot().relationships)
    assert status.object_type_counts["architecture"] == 9
    assert status.object_type_counts["intent"] == 5
    assert status.architecture_without_intent == []


def test_mission_control_status_is_repeatable() -> None:
    registry = build_canonical_brain_fixture()
    assert build_mission_control_status(registry) == build_mission_control_status(registry)
