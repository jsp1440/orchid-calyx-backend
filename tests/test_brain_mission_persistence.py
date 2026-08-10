from pathlib import Path

import pytest

from app.brain_mission.dependencies import build_brain_mission_persistence
from app.brain_mission.persistence import (
    DurableMissionRepository,
    MemoryBrainMissionPersistence,
    MissionEnvelope,
)
from app.brain_mission.service import BrainMissionService, MissionComponents
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


def test_durable_service_repository_round_trips_and_scopes_tenant():
    repository = DurableMissionRepository(MemoryBrainMissionPersistence())
    mission = {
        "mission_id": "mission-key", "tenant_id": "owner-a",
        "project_id": "project-1", "question": "What evidence supports this claim?",
        "limits": {"max_sources": 20, "timeout_seconds": 30},
        "state": "AWAITING_HUMAN_REVIEW", "current_stage": "human_review_state",
    }
    repository.save(mission)
    assert repository.get("mission-key", "owner-a") == mission
    assert repository.get("mission-key", "owner-b") is None
    assert repository.get("mission-key") is None


def test_service_resumes_after_last_durable_stage_without_repeating_it():
    durable = DurableMissionRepository(MemoryBrainMissionPersistence())
    calls = []

    class CrashAfterRetrieval:
        def __init__(self, delegate):
            self.delegate = delegate
            self.crashed = False

        def get(self, *args, **kwargs):
            return self.delegate.get(*args, **kwargs)

        def save(self, mission):
            self.delegate.save(mission)
            if mission["current_stage"] == "evidence_retrieval" and not self.crashed:
                self.crashed = True
                raise RuntimeError("simulated process exit")

    def step(name, output):
        def run(_context):
            calls.append(name)
            return output
        return run

    components = MissionComponents(
        retrieve=step("retrieve", {"results": [{"id": 1}]}),
        aggregate=step("aggregate", {"supporting_evidence": [{"id": 1}]}),
        analyze=step("analyze", {"missing_evidence": []}),
        interpret=step("interpret", {"confidence": 0.8, "conclusions": []}),
        create_ledger=step("ledger", {"ledger_id": "ledger-1", "version": 1}),
        validate=step("validate", {"valid": True, "blockers": []}),
        review_state=step("review", {"status": "HUMAN_REVIEW_REQUIRED"}),
        publication_eligibility=step("eligibility", {"eligible": False}),
    )
    crashing = CrashAfterRetrieval(durable)
    service = BrainMissionService(components, crashing)
    request = {
        "question": "Why?", "tenant_id": "owner",
        "project_id": "project", "actor": "owner",
    }
    with pytest.raises(RuntimeError, match="simulated process exit"):
        service.start(**request)

    result = BrainMissionService(components, durable).start(**request)
    assert result["state"] == "AWAITING_HUMAN_REVIEW"
    assert calls.count("retrieve") == 1
    assert calls.count("aggregate") == 1


def test_subsecond_timeout_is_ceiled_for_database_and_preserved_in_manifest():
    from app.brain_mission.persistence import PostgresBrainMissionPersistence

    class Cursor:
        def __init__(self):
            self.params = None

        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def execute(self, _query, params): self.params = params
        def fetchone(self):
            return {
                "mission_key": "mission-key", "requested_by": "owner-a",
                "version": 1, "input_manifest": self.params[5].obj,
                "output_manifest": {},
            }

    class Connection:
        def __init__(self, cursor): self.value = cursor
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def cursor(self): return self.value

    cursor = Cursor()
    repository = PostgresBrainMissionPersistence("postgresql://configured")
    repository._connect = lambda: Connection(cursor)
    row = repository.create_or_get(
        MissionEnvelope("mission-key", "owner-a", "project-1", "Why?", {"timeout_seconds": 0.1})
    )
    assert cursor.params[4] == 1
    assert row["input_manifest"]["limits"]["timeout_seconds"] == 0.1


def test_migration_registers_type_and_allows_running_to_human_review():
    sql = Path("migrations/108_brain_scientific_mission.sql").read_text()
    assert "'brain_scientific_mission'" in sql
    assert "'running' AND NEW.state IN ('queued','awaiting_approval'" in sql
