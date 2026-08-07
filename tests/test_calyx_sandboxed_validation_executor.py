from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from app.calyx_orchestrator.executor import GovernedAssignment
from app.calyx_orchestrator.executor_registry import AuthoritativeExecutorRegistry
from app.calyx_orchestrator.sandboxed_validation_executor import (
    SANDBOXED_VALIDATION_ROLE,
    SANDBOX_MARKER,
    SandboxedExecutableValidationExecutor,
)

REPOSITORY = "jsp1440/orchid-calyx-backend"
BRANCH = "autonomy/test-validation"
COMMIT = "a" * 40


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".git" / "refs" / "heads" / "autonomy").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text(f"ref: refs/heads/{BRANCH}\n")
    (root / ".git" / "refs" / "heads" / "autonomy" / "test-validation").write_text(
        COMMIT + "\n"
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
        )
    )
    return root


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


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_success_uses_internal_argv_scrubbed_environment_and_hash_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = _workspace(tmp_path)
    target = root / "tests" / "test_example.py"
    target.write_text("def test_ok():\n    assert True\n")
    captured: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, b"one passed\n", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-leak")
    executor = SandboxedExecutableValidationExecutor(
        workspace_root=root,
        repository_name=REPOSITORY,
    )
    receipt = executor.execute(_assignment("tests/test_example.py", _sha(target)))

    assert receipt.state.value == "delivered"
    assert receipt.outcome.value == "DELIVERED"
    assert receipt.executor_key == "isolated_workspace_executable_validator_v1"
    assert receipt.output["preset"] == "pytest"
    assert receipt.output["shell"] is False
    assert receipt.output["environment_inherited"] is False
    assert receipt.output["network_authorized"] is False
    assert receipt.output["credential_access_authorized"] is False
    assert receipt.output["workspace_write_authorized"] is False
    assert receipt.output["return_code"] == 0
    assert "AWS_SECRET_ACCESS_KEY" not in captured["env"]
    assert captured["shell"] is False
    assert captured["stdin"] == subprocess.DEVNULL
    assert tuple(captured["argv"])[1:6] == (
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
    )
    assert target.read_text() == "def test_ok():\n    assert True\n"
    receipt.verify()


def test_nonzero_validation_is_authoritative_blocked_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = _workspace(tmp_path)
    target = root / "app" / "example.py"
    target.write_text("x = 1\n")

    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, b"", b"lint error")

    monkeypatch.setattr(subprocess, "run", fake_run)
    executor = SandboxedExecutableValidationExecutor(
        workspace_root=root,
        repository_name=REPOSITORY,
    )
    receipt = executor.execute(_assignment("app/example.py", _sha(target), preset="ruff"))
    assert receipt.state.value == "blocked"
    assert receipt.outcome.value == "BLOCKED"
    assert receipt.blocker_code == "SANDBOX_VALIDATION_COMMAND_FAILED"
    assert receipt.output["return_code"] == 1
    receipt.verify()


def test_timeout_is_bounded_blocked_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _workspace(tmp_path)
    target = root / "tests" / "test_slow.py"
    target.write_text("def test_slow():\n    pass\n")

    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output=b"partial", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    executor = SandboxedExecutableValidationExecutor(
        workspace_root=root,
        repository_name=REPOSITORY,
    )
    receipt = executor.execute(_assignment("tests/test_slow.py", _sha(target)))
    assert receipt.state.value == "timed_out"
    assert receipt.outcome.value == "BLOCKED"
    assert receipt.blocker_code == "SANDBOX_VALIDATION_COMMAND_TIMEOUT"
    assert receipt.output["timed_out"] is True


def test_marker_is_required_and_must_assert_external_sandbox_enforcement(tmp_path: Path):
    root = _workspace(tmp_path)
    target = root / "tests" / "test_example.py"
    target.write_text("def test_ok():\n    assert True\n")
    marker = json.loads((root / SANDBOX_MARKER).read_text())
    marker["network_disabled"] = False
    (root / SANDBOX_MARKER).write_text(json.dumps(marker))
    executor = SandboxedExecutableValidationExecutor(
        workspace_root=root,
        repository_name=REPOSITORY,
    )
    with pytest.raises(PermissionError, match="SANDBOX_VALIDATION_MARKER_MISMATCH"):
        executor.execute(_assignment("tests/test_example.py", _sha(target)))


def test_arbitrary_command_fields_and_presets_are_rejected(tmp_path: Path):
    root = _workspace(tmp_path)
    target = root / "tests" / "test_example.py"
    target.write_text("def test_ok():\n    assert True\n")
    assignment = _assignment("tests/test_example.py", _sha(target))
    assignment.inputs["job"]["validation"]["command"] = "rm -rf /"  # type: ignore[index]
    executor = SandboxedExecutableValidationExecutor(
        workspace_root=root,
        repository_name=REPOSITORY,
    )
    with pytest.raises(ValueError, match="SANDBOX_VALIDATION_REQUEST_FIELD_NOT_ALLOWED"):
        executor.execute(assignment)

    with pytest.raises(ValueError, match="SANDBOX_VALIDATION_PRESET_NOT_ALLOWED"):
        executor.execute(_assignment("tests/test_example.py", _sha(target), preset="bash"))


def test_stale_hash_and_protected_target_fail_before_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = _workspace(tmp_path)
    target = root / "tests" / "test_example.py"
    target.write_text("def test_ok():\n    assert True\n")
    called = False

    def fake_run(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("subprocess must not run")

    monkeypatch.setattr(subprocess, "run", fake_run)
    executor = SandboxedExecutableValidationExecutor(
        workspace_root=root,
        repository_name=REPOSITORY,
    )
    with pytest.raises(ValueError, match="SANDBOX_VALIDATION_TARGET_HASH_MISMATCH"):
        executor.execute(_assignment("tests/test_example.py", "0" * 64))
    assert called is False

    protected = root / "requirements.txt"
    protected.write_text("requests\n")
    with pytest.raises(PermissionError, match="SANDBOX_VALIDATION_PATH_NOT_ALLOWED"):
        executor.execute(_assignment("requirements.txt", _sha(protected), preset="ruff"))
    assert called is False


def test_mutating_job_and_missing_execution_capability_fail_closed(tmp_path: Path):
    root = _workspace(tmp_path)
    target = root / "tests" / "test_example.py"
    target.write_text("def test_ok():\n    assert True\n")
    executor = SandboxedExecutableValidationExecutor(
        workspace_root=root,
        repository_name=REPOSITORY,
    )

    mutating = _assignment("tests/test_example.py", _sha(target))
    mutating.inputs["job"]["mutating_intent"] = True  # type: ignore[index]
    with pytest.raises(PermissionError, match="SANDBOX_VALIDATION_MUTATING_JOB_PROHIBITED"):
        executor.execute(mutating)

    missing = _assignment("tests/test_example.py", _sha(target))
    object.__setattr__(
        missing,
        "requested_capabilities",
        ("validate_input", "produce_receipt", "collect_evidence_uris"),
    )
    with pytest.raises(PermissionError, match="SANDBOX_VALIDATION_EXECUTION_CAPABILITY_REQUIRED"):
        executor.execute(missing)


def test_registry_truthfully_marks_only_sandbox_validator_as_code_execution(tmp_path: Path):
    root = _workspace(tmp_path)
    registry = AuthoritativeExecutorRegistry(workspace_root=root, repository_name=REPOSITORY)
    status = registry.status()
    by_role = {item["role_key"]: item for item in status["executors"]}
    assert by_role[SANDBOXED_VALIDATION_ROLE]["repository_code_execution"] is True
    assert by_role["isolated_workspace_static_validator"]["repository_code_execution"] is False
    assert by_role["isolated_workspace_patcher"]["workspace_mutation"] is True
