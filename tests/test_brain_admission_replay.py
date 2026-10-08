"""Offline regressions for replaying admitted Brain work without duplication."""

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.calyx_orchestrator.program_models import (
    CalyxProgram,
    CalyxProgramDependency,
    CalyxProgramJob,
)
from app.calyx_orchestrator.program_repository import (
    PersistentProgramRepository,
    ProgramJobSpec,
)
from app.canonical_brain.build_queue import GovernedBuildQueue
from app.canonical_brain.constitution import BuildAdmissionRequest
from app.database import Base


def admission(**overrides):
    return BuildAdmissionRequest(
        build_id="build:brain-replay",
        architecture_id="architecture:lexicon",
        intent_ids=["intent:verification"],
        decision_ids=["decision:verification"],
        source_uris=["fixture:source"],
        validation_plan_ids=["validation:static"],
        deterministic_outputs=True,
        preserves_provenance=True,
        separates_evidence_from_inference=True,
        **overrides,
    )


@pytest.mark.parametrize("status", ["scheduled", "running", "completed", "cancelled"])
def test_build_replay_preserves_progress(status):
    queue = GovernedBuildQueue()
    queue.submit(admission())
    for step in ["scheduled", "running", "completed"]:
        if status == "cancelled":
            queue.transition(admission().build_id, "cancelled")
            break
        queue.transition(admission().build_id, step)
        if step == status:
            break
    replay = queue.submit(admission())
    assert replay.status == status
    assert len(queue.snapshot().items) == 1


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'replay.db'}")
    Base.metadata.create_all(engine, tables=[
        CalyxProgram.__table__, CalyxProgramJob.__table__,
        CalyxProgramDependency.__table__,
    ])
    with Session(engine) as session:
        yield session
    engine.dispose()


def specification(**overrides):
    return {
        "owner": "fixture-owner", "title": "Brain verification",
        "objective": "Replay the same admitted work",
        "jobs": [ProgramJobSpec("check", "backend_engineer", "Check", "fixture/repo")],
        "dependencies": [],
        "idempotency_key": "build:brain-replay",
        **overrides,
    }


def test_persisted_admission_replays_across_sessions_and_does_not_restart(db):
    repository = PersistentProgramRepository(db)
    program = repository.create_program(**specification())
    repository.start(owner="fixture-owner", program_id=program.program_id)
    repository.record_outcome(
        owner="fixture-owner", program_id=program.program_id, job_key="check",
        outcome="DELIVERED", evidence={"fixture": True},
    )
    with Session(db.get_bind()) as second:
        replay = PersistentProgramRepository(second).create_program(**specification())
        assert replay.program_id == program.program_id
        assert replay.status == "completed"
        assert second.scalar(select(func.count()).select_from(CalyxProgram)) == 1
        assert second.scalar(select(func.count()).select_from(CalyxProgramJob)) == 1


def test_persisted_identity_conflict_is_rejected_and_owner_is_isolated(db):
    repository = PersistentProgramRepository(db)
    first = repository.create_program(**specification())
    with pytest.raises(ValueError, match="IDEMPOTENCY_CONFLICT"):
        repository.create_program(**specification(objective="Different work"))
    second = repository.create_program(**specification(owner="other-fixture-owner"))
    assert first.program_id != second.program_id


def request_payload(**overrides):
    from app.calyx_orchestrator.program_routes import ProgramRequest
    return ProgramRequest(
        title="Brain verification", objective="Verify the source snapshot",
        jobs=[{
            "job_key": "verify", "role_key": "repository_evidence_reader",
            "title": "Verify", "repository": "fixture/repo",
            "inputs": {"files": [{"path": "app/example.py", "sha256": "a" * 64}]},
        }],
        admission=admission(), **overrides,
    )


def test_program_api_handoff_is_idempotent_and_preserves_admission(db):
    from app.calyx_orchestrator.program_routes import create_program
    auth = {"subject": "fixture-owner"}
    create_program(request_payload(), auth, db)
    first = db.scalar(select(CalyxProgram))
    job = db.scalar(select(CalyxProgramJob))
    assert '"brain_admission"' in job.input_json
    PersistentProgramRepository(db).record_outcome(
        owner="fixture-owner", program_id=first.program_id, job_key="verify",
        outcome="DELIVERED", evidence={"fixture": True},
    )
    create_program(request_payload(), auth, db)
    db.refresh(first)
    assert first.status == "completed"
    assert db.scalar(select(func.count()).select_from(CalyxProgramJob)) == 1


@pytest.mark.parametrize("authority", [
    "publication_requested", "deployment_requested", "merge_requested",
    "production_graph_mutation_requested",
])
def test_program_api_rejects_governed_actions_without_persistence(db, authority):
    from fastapi import HTTPException
    from app.calyx_orchestrator.program_routes import create_program
    payload = request_payload()
    payload.admission = admission(**{authority: True})
    with pytest.raises(HTTPException) as error:
        create_program(payload, {"subject": "fixture-owner"}, db)
    assert error.value.status_code == 403
    assert db.scalar(select(func.count()).select_from(CalyxProgram)) == 0
