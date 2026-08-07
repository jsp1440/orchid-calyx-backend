from __future__ import annotations

import hashlib

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.assignment_factory import (
    governed_assignment_from_claimed_job,
)
from app.calyx_orchestrator.program_models import (
    CalyxProgram,
    CalyxProgramDependency,
    CalyxProgramJob,
)
from app.calyx_orchestrator.program_repository import (
    PersistentProgramRepository,
    ProgramJobSpec,
)
from app.calyx_orchestrator.program_worker import PersistentProgramWorker
from app.calyx_orchestrator.sandboxed_validation_executor import (
    SANDBOXED_VALIDATION_ROLE,
)
from app.database import Base


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[CalyxProgram.__table__, CalyxProgramJob.__table__, CalyxProgramDependency.__table__],
    )
    return Session(engine)


def test_persisted_sandbox_validation_job_receives_only_bounded_execution_capability():
    digest = hashlib.sha256(b"def test_ok():\n    assert True\n").hexdigest()
    with _db() as db:
        repository = PersistentProgramRepository(db)
        program = repository.create_program(
            owner="owner",
            title="Sandboxed validation",
            objective="Run fixed validation preset after bounded patching.",
            jobs=[
                ProgramJobSpec(
                    job_key="validate",
                    role_key=SANDBOXED_VALIDATION_ROLE,
                    title="Validate exact postimage",
                    repository="jsp1440/orchid-calyx-backend",
                    branch="autonomy/test-validation",
                    mutating=False,
                    inputs={
                        "validation": {
                            "preset": "pytest",
                            "targets": ["tests/test_example.py"],
                            "expected_sha256": {"tests/test_example.py": digest},
                            "timeout_seconds": 30,
                        }
                    },
                )
            ],
            dependencies=[],
        )
        repository.start(owner="owner", program_id=program.program_id)
        job = PersistentProgramWorker(db).claim(
            worker_id="worker",
            owner="owner",
            allowed_role_keys=frozenset({SANDBOXED_VALIDATION_ROLE}),
        )
        assert job is not None
        assignment = governed_assignment_from_claimed_job(
            db,
            owner="owner",
            job=job,
            timeout_seconds=60,
        )
        assert assignment.role_key == SANDBOXED_VALIDATION_ROLE
        assert "repository_code_execution" in assignment.requested_capabilities
        assert "workspace_write" not in assignment.requested_capabilities
        governance = assignment.inputs["governance"]
        assert governance["repository_code_execution_authorized"] is True
        assert governance["workspace_write_authorized"] is False
        job_payload = assignment.inputs["job"]
        assert job_payload["repository"] == "jsp1440/orchid-calyx-backend"
        assert job_payload["branch"] == "autonomy/test-validation"
        assert job_payload["validation"]["preset"] == "pytest"


def test_unrelated_role_does_not_gain_repository_code_execution_capability():
    with _db() as db:
        repository = PersistentProgramRepository(db)
        program = repository.create_program(
            owner="owner",
            title="Read-only probe",
            objective="No executable validation authority.",
            jobs=[
                ProgramJobSpec(
                    job_key="probe",
                    role_key="autonomy_probe",
                    title="Probe",
                    repository="jsp1440/orchid-calyx-backend",
                    branch="autonomy/test-validation",
                    mutating=False,
                )
            ],
            dependencies=[],
        )
        repository.start(owner="owner", program_id=program.program_id)
        job = PersistentProgramWorker(db).claim(
            worker_id="worker",
            owner="owner",
            allowed_role_keys=frozenset({"autonomy_probe"}),
        )
        assert job is not None
        assignment = governed_assignment_from_claimed_job(db, owner="owner", job=job)
        assert "repository_code_execution" not in assignment.requested_capabilities
        assert assignment.inputs["governance"]["repository_code_execution_authorized"] is False
