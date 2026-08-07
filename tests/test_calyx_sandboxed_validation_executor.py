from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.executor import GovernedAssignment
from app.calyx_orchestrator.executor_registry import AuthoritativeExecutorRegistry
from app.calyx_orchestrator.program_cycle import run_deterministic_program_cycle
from app.calyx_orchestrator.program_models import (
    CalyxProgram,
    CalyxProgramDependency,
    CalyxProgramJob,
)
from app.calyx_orchestrator.program_repository import (
    PersistentProgramRepository,
    ProgramJobSpec,
)
from app.calyx_orchestrator.sandbox_authorization import SandboxAuthorization
from app.calyx_orchestrator.sandboxed_validation_executor import (
    SANDBOX_MARKER,
    SANDBOXED_VALIDATION_ROLE,
    SandboxedExecutableValidationExecutor,
)
from app.database import Base

REPOSITORY = "jsp1440/orchid-calyx-backend"
BRANCH = "autonomy/test-validation"
COMMIT = "a" * 40
POLICY_DIGEST = "b" * 64


class AllowingAuthorizer:
    def authorize(self, *, workspace_root, repository, branch, marker, request_digest):
        assert workspace_root.is_dir()
        assert repository == REPOSITORY
        assert branch == BRANCH
        assert marker["network_disabled"] is True
        assert marker["repository_read_only_during_validation"] is True
        assert len(request_digest) == 64
        return SandboxAuthorization(
            authorization_id="auth-1",
            evidence_uri="sandbox-supervisor:auth-1",
            policy_digest=POLICY_DIGEST,
            request_digest=request_digest,
        )


class RejectingAuthorizer:
    def authorize(self, **kwargs):
        raise PermissionError("sandbox not enforced")


class StaleAuthorizer:
    def authorize(self, **kwargs):
        return SandboxAuthorization(
            authorization_id="stale-auth",
            evidence_uri="sandbox-supervisor:stale-auth",
            policy_digest=POLICY_DIGEST,
            request_digest="c" * 64,
        )


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".git" / "refs" / "heads" / "autonomy").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text(f"ref: refs/heads/{BRANCH}\n", encoding="ascii")
    (root / ".git" / "refs" / "heads" / "autonomy" / "test-validation").write_text(
        COMMIT + "\n", encoding="ascii"
    )
    (root / "tests").mkdir()
    (root / "app").mkdir()
    (root / SANDBOX_MARKER).write_text(
        json.dumps(
            {
                "schema": "calyx-validation-sandbox-v1",
                "repository": REPOSITORY,
                "branch": BRANCH,
                "disposable": True,
                "network_disabled": True,
                "credentials_absent": True,
                "shell_disabled": True,
                "package_installation_disabled": True,
                "subprocess_confinement_enforced": True,
                "repository_read_only_during_validation": True,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return root


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assignment(path: str, digest: str, *, preset: str = "pytest") -> GovernedAssignment:
    return GovernedAssignment(
        assignment_id="assignment-1",
        program_id="program-1",
        job_key="validate",
        role_key=SANDBOXED_VALIDATION_ROLE,
        objective="Run bounded executable validation",
        inputs={
            "job": {
                "repository": REPOSITORY,
                "branch": BRANCH,
                "mutating_intent": False,
                "validation": {
                    "preset": preset,
                    "targets": [path],
                    "expected_sha256": {path: digest},
                    "timeout_seconds": 30,
                },
            }
        },
        requested_capabilities=(
            "validate_input",
            "produce_receipt",
            "collect_evidence_uris",
            "repository_code_execution",
        ),
        evidence_uris=("calyx:test",),
        timeout_seconds=60,
    )


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[CalyxProgram.__table__, CalyxProgramJob.__table__, CalyxProgramDependency.__table__],
    )
    return Session(engine)


def test_marker_alone_never_authorizes_subprocess(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _workspace(tmp_path)
    target = root / "tests" / "test_example.py"
    target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    called = False

    def fake_run(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("subprocess must not run")

    monkeypatch.setattr(subprocess, "run", fake_run)
    executor = SandboxedExecutableValidationExecutor(workspace_root=root, repository_name=REPOSITORY)
    with pytest.raises(PermissionError, match="SANDBOX_VALIDATION_SUPERVISOR_REQUIRED"):
        executor.execute(_assignment("tests/test_example.py", _sha(target)))
    assert called is False


def test_supervisor_authorized_success_uses_fixed_argv_and_scrubbed_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = _workspace(tmp_path)
    target = root / "tests" / "test_example.py"
    target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = tuple(argv)
        captured.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, b"one passed\n", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-leak")
    executor = SandboxedExecutableValidationExecutor(
        workspace_root=root,
        repository_name=REPOSITORY,
        authorizer=AllowingAuthorizer(),
    )
    receipt = executor.execute(_assignment("tests/test_example.py", _sha(target)))
    assert receipt.state.value == "delivered"
    assert receipt.output["supervisor_authorized"] is True
    assert receipt.output["supervisor_authorization_id"] == "auth-1"
    assert receipt.output["sandbox_policy_digest"] == POLICY_DIGEST
    request_digest = receipt.output["supervisor_request_digest"]
    assert isinstance(request_digest, str) and len(request_digest) == 64
    assert f"sandbox-request:{request_digest}" in receipt.evidence_uris
    assert "sandbox-supervisor:auth-1" in receipt.evidence_uris
    assert captured["shell"] is False
    assert captured["stdin"] == subprocess.DEVNULL
    assert "AWS_SECRET_ACCESS_KEY" not in captured["env"]
    assert captured["argv"][1:6] == ("-m", "pytest", "-q", "-p", "no:cacheprovider")
    receipt.verify()


def test_rejected_or_stale_supervisor_authorization_fails_before_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = _workspace(tmp_path)
    target = root / "tests" / "test_example.py"
    target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    called = False

    def fake_run(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("subprocess must not run")

    monkeypatch.setattr(subprocess, "run", fake_run)
    rejecting = SandboxedExecutableValidationExecutor(
        workspace_root=root, repository_name=REPOSITORY, authorizer=RejectingAuthorizer()
    )
    with pytest.raises(PermissionError, match="SANDBOX_VALIDATION_SUPERVISOR_REJECTED"):
        rejecting.execute(_assignment("tests/test_example.py", _sha(target)))

    stale = SandboxedExecutableValidationExecutor(
        workspace_root=root, repository_name=REPOSITORY, authorizer=StaleAuthorizer()
    )
    with pytest.raises(PermissionError, match="SANDBOX_VALIDATION_SUPERVISOR_REJECTED"):
        stale.execute(_assignment("tests/test_example.py", _sha(target)))
    assert called is False


def test_stale_target_hash_fails_before_supervisor_or_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = _workspace(tmp_path)
    target = root / "tests" / "test_example.py"
    target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    called = False

    class ShouldNotAuthorize:
        def authorize(self, **kwargs):
            nonlocal called
            called = True
            raise AssertionError("supervisor must not be called")

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    executor = SandboxedExecutableValidationExecutor(
        workspace_root=root, repository_name=REPOSITORY, authorizer=ShouldNotAuthorize()
    )
    with pytest.raises(ValueError, match="SANDBOX_VALIDATION_TARGET_HASH_MISMATCH"):
        executor.execute(_assignment("tests/test_example.py", "0" * 64))
    assert called is False


def test_arbitrary_command_and_preset_are_rejected(tmp_path: Path):
    root = _workspace(tmp_path)
    target = root / "tests" / "test_example.py"
    target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    executor = SandboxedExecutableValidationExecutor(
        workspace_root=root, repository_name=REPOSITORY, authorizer=AllowingAuthorizer()
    )
    assignment = _assignment("tests/test_example.py", _sha(target))
    assignment.inputs["job"]["validation"]["command"] = "rm -rf /"  # type: ignore[index]
    with pytest.raises(ValueError, match="SANDBOX_VALIDATION_REQUEST_FIELD_NOT_ALLOWED"):
        executor.execute(assignment)
    with pytest.raises(ValueError, match="SANDBOX_VALIDATION_PRESET_NOT_ALLOWED"):
        executor.execute(_assignment("tests/test_example.py", _sha(target), preset="bash"))


def test_nonzero_and_timeout_return_authoritative_blocked_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = _workspace(tmp_path)
    target = root / "tests" / "test_example.py"
    target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    executor = SandboxedExecutableValidationExecutor(
        workspace_root=root, repository_name=REPOSITORY, authorizer=AllowingAuthorizer()
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 1, b"failed", b""),
    )
    failed = executor.execute(_assignment("tests/test_example.py", _sha(target)))
    assert failed.state.value == "blocked"
    assert failed.blocker_code == "SANDBOX_VALIDATION_COMMAND_FAILED"

    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output=b"partial", stderr=b"")

    monkeypatch.setattr(subprocess, "run", timeout)
    timed = executor.execute(_assignment("tests/test_example.py", _sha(target)))
    assert timed.state.value == "timed_out"
    assert timed.blocker_code == "SANDBOX_VALIDATION_COMMAND_TIMEOUT"


def test_default_registry_cannot_claim_executable_validation_job(tmp_path: Path):
    root = _workspace(tmp_path)
    target = root / "tests" / "test_example.py"
    target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    default_registry = AuthoritativeExecutorRegistry(workspace_root=root, repository_name=REPOSITORY)
    assert SANDBOXED_VALIDATION_ROLE not in default_registry.eligible_role_keys
    assert default_registry.status()["sandboxed_repository_code_execution_authorized"] is False

    with _db() as db:
        repository = PersistentProgramRepository(db)
        program = repository.create_program(
            owner="owner",
            title="No supervisor",
            objective="Executable validation remains queued without supervisor authority.",
            jobs=[
                ProgramJobSpec(
                    "validate",
                    SANDBOXED_VALIDATION_ROLE,
                    "Validate",
                    REPOSITORY,
                    BRANCH,
                    False,
                    {
                        "validation": {
                            "preset": "pytest",
                            "targets": ["tests/test_example.py"],
                            "expected_sha256": {"tests/test_example.py": _sha(target)},
                        }
                    },
                )
            ],
            dependencies=[],
        )
        repository.start(owner="owner", program_id=program.program_id)
        result = run_deterministic_program_cycle(
            db, owner="owner", worker_id="worker", registry=default_registry
        )
        assert result.completed_jobs == 0
        job = db.query(CalyxProgramJob).filter(CalyxProgramJob.program_id == program.program_id).one()
        assert job.status == "queued"
        assert job.attempt_count == 0


def test_authorized_registry_exposes_code_execution_role(tmp_path: Path):
    root = _workspace(tmp_path)
    registry = AuthoritativeExecutorRegistry(
        workspace_root=root,
        repository_name=REPOSITORY,
        sandbox_validation_authorizer=AllowingAuthorizer(),
    )
    assert SANDBOXED_VALIDATION_ROLE in registry.eligible_role_keys
    status = registry.status()
    by_role = {row["role_key"]: row for row in status["executors"]}
    assert status["sandboxed_repository_code_execution_authorized"] is True
    assert by_role[SANDBOXED_VALIDATION_ROLE]["repository_code_execution"] is True
    assert by_role["isolated_workspace_static_validator"]["repository_code_execution"] is False
