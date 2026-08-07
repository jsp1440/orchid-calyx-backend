from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.calyx_orchestrator.models import CalyxJob
from app.calyx_orchestrator.operations import operational_status
from app.calyx_orchestrator.program_models import (
    CalyxProgram,
    CalyxProgramDependency,
    CalyxProgramJob,
)


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CalyxJob.__table__,
            CalyxProgram.__table__,
            CalyxProgramJob.__table__,
            CalyxProgramDependency.__table__,
        ],
    )
    return Session(engine)


def test_mission_control_reports_program_slots_and_repository_usage() -> None:
    db = _session()
    program = CalyxProgram(
        owner="owner-1",
        title="Parallel repair",
        objective="Run bounded engineering work.",
        status="running",
        max_active_jobs=6,
    )
    db.add(program)
    db.flush()
    db.add_all(
        [
            CalyxProgramJob(
                program_id=program.program_id,
                job_key="frontend",
                role_key="frontend_engineer",
                title="Repair frontend",
                repository="jsp1440/orchid-continuum-frontend",
                branch="fix/frontend",
                mutating=True,
                work_fingerprint="a" * 64,
                status="running",
            ),
            CalyxProgramJob(
                program_id=program.program_id,
                job_key="backend",
                role_key="backend_engineer",
                title="Repair backend",
                repository="jsp1440/orchid-calyx-backend",
                branch="fix/backend",
                mutating=True,
                work_fingerprint="b" * 64,
                status="running",
            ),
            CalyxProgramJob(
                program_id=program.program_id,
                job_key="director",
                role_key="engineering_director",
                title="Consolidate report",
                repository="jsp1440/orchid-calyx-backend",
                mutating=False,
                work_fingerprint="c" * 64,
                status="waiting",
            ),
        ]
    )
    db.commit()

    status = operational_status(db, owner="owner-1")["engineering_programs"]

    assert status["active_slots"] == {"used": 2, "available": 4, "limit": 6}
    assert status["dependency_waiting_jobs"] == 1
    assert {item["repository"] for item in status["repository_slots"]} == {
        "jsp1440/orchid-calyx-backend",
        "jsp1440/orchid-continuum-frontend",
    }


def test_mission_control_surfaces_exact_human_action_for_blocked_job() -> None:
    db = _session()
    program = CalyxProgram(
        owner="owner-1",
        title="Blocked program",
        objective="Demonstrate blocker reporting.",
        status="blocked",
    )
    db.add(program)
    db.flush()
    db.add(
        CalyxProgramJob(
            program_id=program.program_id,
            job_key="graph",
            role_key="knowledge_graph_engineer",
            title="Publish graph",
            repository="jsp1440/orchid-calyx-backend",
            branch="feature/graph",
            mutating=True,
            work_fingerprint="d" * 64,
            status="blocked",
            outcome="BLOCKED",
            blocker="OWNER_APPROVAL_REQUIRED",
            human_action="Approve the reviewed graph publication ledger.",
        )
    )
    db.commit()

    status = operational_status(db, owner="owner-1")["engineering_programs"]

    assert status["blockers"][0]["blocker"] == "OWNER_APPROVAL_REQUIRED"
    assert status["exact_human_actions"] == [
        "Approve the reviewed graph publication ledger."
    ]
