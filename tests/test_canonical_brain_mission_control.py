from __future__ import annotations

from app.canonical_brain import (
    build_canonical_brain_fixture,
    build_mission_control_status,
)


def test_mission_control_status_reports_brain_coverage() -> None:
    registry = build_canonical_brain_fixture()

    status = build_mission_control_status(registry)

    assert status.mode == "read-only-candidate"
    assert status.persistence_enabled is False
    assert status.publication_enabled is False
    assert status.object_count == len(registry.snapshot().objects)
    assert status.relationship_count == len(registry.snapshot().relationships)
    assert status.object_type_counts["architecture"] >= 8
    assert status.object_type_counts["intent"] == 2
    assert status.lifecycle_counts == {"approved": status.object_count}
    assert "architecture:atlas" not in status.architecture_without_intent
    assert "architecture:mission-control" in status.architecture_without_intent


def test_mission_control_status_is_repeatable() -> None:
    registry = build_canonical_brain_fixture()

    first = build_mission_control_status(registry)
    second = build_mission_control_status(registry)

    assert first == second
