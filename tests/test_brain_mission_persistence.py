import pytest

from app.brain_mission.dependencies import build_brain_mission_persistence
from app.brain_mission.persistence import MemoryBrainMissionPersistence, MissionEnvelope
from app.missions.registry import MISSION_TYPES


def envelope(owner="owner-a"):
    return MissionEnvelope(
        mission_key="mission-key",
        owner=owner,
        project_id="project-1",
        question="What evidence supports this orchid claim?",
        limits={"max_sources": 20, "timeout_seconds": 30},
    )


def test_brain_mission_type_preserves_review_and_write_boundaries():
    mission_type = MISSION_TYPES["brain_scientific_mission"]
    assert mission_type.human_approval_required is True
    assert mission_type.canonical_graph_writes_permitted is False
    assert mission_type.taxonomy_writes_prohibited is True


def test_memory_envelope_is_owner_scoped_and_idempotent():
    repository = MemoryBrainMissionPersistence()
    first = repository.create_or_get(envelope())
    assert repository.create_or_get(envelope()) == first
    assert repository.get("mission-key", "owner-b") is None
    with pytest.raises(LookupError, match="MISSION_NOT_FOUND"):
        repository.create_or_get(envelope("owner-b"))


def test_checkpoint_uses_optimistic_version_and_records_stage():
    repository = MemoryBrainMissionPersistence()
    repository.create_or_get(envelope())
    updated = repository.checkpoint(
        "mission-key",
        "owner-a",
        expected_version=1,
        state="awaiting_approval",
        output={"interpretation_id": 42},
        stage="scientific_interpretation",
    )
    assert updated["version"] == 2
    assert updated["output_manifest"] == {
        "interpretation_id": 42,
        "checkpoint_stage": "scientific_interpretation",
    }
    with pytest.raises(RuntimeError, match="MISSION_VERSION_CONFLICT"):
        repository.checkpoint(
            "mission-key",
            "owner-a",
            expected_version=1,
            state="completed",
            output={},
            stage="validation",
        )


def test_dependency_fails_closed_without_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
        build_brain_mission_persistence()
