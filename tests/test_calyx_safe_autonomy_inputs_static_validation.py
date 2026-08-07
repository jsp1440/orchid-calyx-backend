from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.assignment_factory import (
    governed_assignment_from_claimed_job,
)
from app.calyx_orchestrator.executor import GovernedAssignment
from app.calyx_orchestrator.executor_registry import AuthoritativeExecutorRegistry
from app.calyx_orchestrator.isolated_patch_executor import (
    ISOLATION_MARKER,
    ISOLATION_SCHEMA,
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
from app.calyx_orchestrator.static_validation_executor import (
    STATIC_VALIDATION_ROLE,
    IsolatedWorkspaceStaticValidationExecutor,
)
from app.database import Base

REPOSITORY = "jsp1440/orchid-calyx-backend"
BRANCH = "autonomy/static-validation"
COMMIT = "a" * 40


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[CalyxProgram.__table__, CalyxProgramJob.__table__, CalyxProgramDependency.__table__],
    )
    return Session(engine)


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    ref = root / ".git" / "refs" / "heads" / "autonomy" / "static-validation"
    ref.parent.mkdir(parents=True)
    (root / ".git" / "HEAD").write_text(f"ref: refs/heads/{BRANCH}\n", encoding="ascii")
    ref.write_text(COMMIT + "\n", encoding="ascii")
    (root / "tests").mkdir()
    (root / "app").mkdir()
    (root / ISOLATION_MARKER).write_text(
        json.dumps(
            {
                "schema": ISOLATION_SCHEMA,
                "repository": REPOSITORY,
                "branch": BRANCH,
                "disposable": True,
                "workspace_write_authorized": True,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return root


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_job_inputs_are_canonical_persisted_and_snapshot_redacts_values() -> None:
    with _db() as db:
        repository = PersistentProgramRepository(db)
        spec = ProgramJobSpec(
            job_key="inspect",
            role_key="repository_evidence_reader",
            title="Inspect evidence",
            repository=REPOSITORY,
            branch="autonomy/evidence",
            inputs={"paths": ["app/main.py"], "note": "bounded"},
        )
        program = repository.create_program(
            owner="owner",
            title="Persisted inputs",
            objective="Persist bounded job manifests.",
            jobs=[spec],
            dependencies=[],
        )
        job = db.query(CalyxProgramJob).filter_by(program_id=program.program_id).one()
        assert json.loads(job.input_json or "{}") == {
            "note": "bounded",
            "paths": ["app/main.py"],
        }
        snapshot = repository.snapshot(owner="owner", program_id=program.program_id)
        row = snapshot["jobs"][0]
        assert row["input_manifest_present"] is True
        assert row["input_manifest_keys"] == ["note", "paths"]
        assert len(row["input_manifest_sha256"]) == 64
        assert "bounded" not in json.dumps(row)
        assert "app/main.py" not in json.dumps(row)


def test_inputs_change_fingerprint_and_invalid_json_values_fail_closed() -> None:
    base = ProgramJobSpec("job", "role", "Title", REPOSITORY, inputs={"x": 1})
    changed = ProgramJobSpec("job", "role", "Title", REPOSITORY, inputs={"x": 2})
    assert base.fingerprint != changed.fingerprint
    with pytest.raises(ValueError, match="PROGRAM_JOB_INPUTS_NOT_CANONICAL_JSON"):
        _ = ProgramJobSpec(
            "job", "role", "Title", REPOSITORY, inputs={"x": float("nan")}
        ).serialized_inputs


def test_claimed_assignment_projects_inputs_but_reserved_keys_fail_closed() -> None:
    with _db() as db:
        repository = PersistentProgramRepository(db)
        program = repository.create_program(
            owner="owner",
            title="Assignment inputs",
            objective="Project persisted inputs into the governed assignment.",
            jobs=[
                ProgramJobSpec(
                    "inspect",
                    "repository_evidence_reader",
                    "Inspect",
                    REPOSITORY,
                    "autonomy/evidence",
                    False,
                    {"paths": ["app/main.py"]},
                )
            ],
            dependencies=[],
        )
        repository.start(owner="owner", program_id=program.program_id)
        job = PersistentProgramWorker(db).claim(worker_id="worker", lease_seconds=300, owner="owner")
        assert job is not None
        assignment = governed_assignment_from_claimed_job(db, owner="owner", job=job)
        assert assignment.inputs["job"]["paths"] == ["app/main.py"]
        assert assignment.inputs["governance"]["repository_code_execution_authorized"] is False
        assert "repository_code_execution" not in assignment.requested_capabilities

        job.input_json = json.dumps({"repository": "attacker/repo"})
        db.commit()
        with pytest.raises(PermissionError, match="PROGRAM_JOB_INPUT_RESERVED_KEY:repository"):
            governed_assignment_from_claimed_job(db, owner="owner", job=job)


def test_default_registry_exposes_static_validation_but_never_code_execution(tmp_path: Path) -> None:
    registry = AuthoritativeExecutorRegistry(workspace_root=_workspace(tmp_path), repository_name=REPOSITORY)
    assert STATIC_VALIDATION_ROLE in registry.eligible_role_keys
    status = registry.status()
    assert status["sandboxed_repository_code_execution_authorized"] is False
    by_role = {row["role_key"]: row for row in status["executors"]}
    assert by_role[STATIC_VALIDATION_ROLE]["repository_code_execution"] is False
    assert all(row["repository_code_execution"] is False for row in status["executors"])


def test_static_validator_parses_python_without_import_subprocess_network_or_write(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    target = root / "tests" / "test_example.py"
    target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    assignment = GovernedAssignment(
        assignment_id="assignment-1",
        program_id="program-1",
        job_key="static",
        role_key=STATIC_VALIDATION_ROLE,
        objective="Validate syntax only",
        inputs={
            "job": {
                "repository": REPOSITORY,
                "branch": BRANCH,
                "mutating_intent": False,
                "files": [{"path": "tests/test_example.py", "sha256": _digest(target)}],
            }
        },
        requested_capabilities=("validate_input", "produce_receipt", "collect_evidence_uris"),
        evidence_uris=("calyx:test",),
        timeout_seconds=60,
    )
    before = target.read_bytes()
    receipt = IsolatedWorkspaceStaticValidationExecutor(
        workspace_root=root,
        repository_name=REPOSITORY,
    ).execute(assignment)
    assert receipt.state.value == "delivered"
    assert receipt.output["repository_code_imported"] is False
    assert receipt.output["repository_code_executed"] is False
    assert receipt.output["subprocess_invoked"] is False
    assert receipt.output["shell_invoked"] is False
    assert receipt.output["network_used"] is False
    assert receipt.output["files_written"] is False
    assert target.read_bytes() == before


def test_static_validator_rejects_invalid_syntax_and_hash_drift(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    target = root / "app" / "broken.py"
    target.write_text("def broken(:\n", encoding="utf-8")
    executor = IsolatedWorkspaceStaticValidationExecutor(workspace_root=root, repository_name=REPOSITORY)

    def assignment(digest: str) -> GovernedAssignment:
        return GovernedAssignment(
            assignment_id="assignment-2",
            program_id="program-1",
            job_key="static",
            role_key=STATIC_VALIDATION_ROLE,
            objective="Reject invalid source",
            inputs={
                "job": {
                    "repository": REPOSITORY,
                    "branch": BRANCH,
                    "mutating_intent": False,
                    "files": [{"path": "app/broken.py", "sha256": digest}],
                }
            },
            requested_capabilities=("validate_input",),
            evidence_uris=(),
            timeout_seconds=60,
        )

    with pytest.raises(ValueError, match="STATIC_VALIDATION_HASH_MISMATCH"):
        executor.execute(assignment("0" * 64))
    with pytest.raises(ValueError, match="STATIC_VALIDATION_PYTHON_SYNTAX_INVALID"):
        executor.execute(assignment(_digest(target)))
