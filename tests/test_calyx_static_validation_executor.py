from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.calyx_orchestrator.executor import ExecutionState, GovernedAssignment
from app.calyx_orchestrator.executor_registry import AuthoritativeExecutorRegistry
from app.calyx_orchestrator.static_validation_executor import (
    STATIC_VALIDATION_ROLE,
    IsolatedWorkspaceStaticValidationExecutor,
)

REPOSITORY = "jsp1440/orchid-calyx-backend"
BRANCH = "autonomy/static-validation"
COMMIT = "b" * 40


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "worktree"
    (root / ".git" / "refs" / "heads" / "autonomy").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text(f"ref: refs/heads/{BRANCH}\n", encoding="ascii")
    (root / ".git" / "refs" / "heads" / "autonomy" / "static-validation").write_text(
        COMMIT + "\n", encoding="ascii"
    )
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "docs" / "brain").mkdir(parents=True)
    (root / ".calyx-isolated-workspace.json").write_text(
        json.dumps(
            {
                "schema": "calyx-isolated-workspace-v1",
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


def _assignment(*files: dict, branch: str = BRANCH) -> GovernedAssignment:
    return GovernedAssignment(
        assignment_id="assignment-114d",
        program_id="program-114d",
        job_key="job-114d",
        role_key=STATIC_VALIDATION_ROLE,
        objective="Statically validate isolated patch outputs",
        inputs={
            "job": {
                "repository": REPOSITORY,
                "branch": branch,
                "mutating_intent": False,
                "files": list(files),
            }
        },
        requested_capabilities=("validate_input", "produce_receipt"),
        evidence_uris=("brain-build:BUILD-BRAIN-114D",),
    )


def test_python_file_hash_and_syntax_validate_without_execution(tmp_path: Path):
    root = _workspace(tmp_path)
    source = b"VALUE = 42\n"
    target = root / "app" / "example.py"
    target.write_bytes(source)
    executor = IsolatedWorkspaceStaticValidationExecutor(
        workspace_root=root,
        repository_name=REPOSITORY,
    )
    receipt = executor.execute(
        _assignment({"path": "app/example.py", "sha256": _sha(source)})
    )
    assert receipt.state == ExecutionState.DELIVERED
    result = receipt.output["results"][0]
    assert result["language"] == "python"
    assert result["syntax"] == "passed"
    assert receipt.output["repository_code_executed"] is False
    assert receipt.output["subprocess_invoked"] is False
    assert receipt.output["files_written"] is False
    receipt.verify()


def test_invalid_python_syntax_fails_closed(tmp_path: Path):
    root = _workspace(tmp_path)
    source = b"def broken(:\n    pass\n"
    target = root / "tests" / "test_broken.py"
    target.write_bytes(source)
    executor = IsolatedWorkspaceStaticValidationExecutor(
        workspace_root=root,
        repository_name=REPOSITORY,
    )
    with pytest.raises(ValueError, match="PYTHON_SYNTAX_INVALID"):
        executor.execute(
            _assignment({"path": "tests/test_broken.py", "sha256": _sha(source)})
        )


def test_hash_mismatch_is_rejected(tmp_path: Path):
    root = _workspace(tmp_path)
    target = root / "app" / "example.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    executor = IsolatedWorkspaceStaticValidationExecutor(
        workspace_root=root,
        repository_name=REPOSITORY,
    )
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        executor.execute(
            _assignment({"path": "app/example.py", "sha256": "0" * 64})
        )


def test_non_python_text_is_utf8_and_hash_validated(tmp_path: Path):
    root = _workspace(tmp_path)
    source = b"# Brain evidence\n"
    target = root / "docs" / "brain" / "evidence.md"
    target.write_bytes(source)
    executor = IsolatedWorkspaceStaticValidationExecutor(
        workspace_root=root,
        repository_name=REPOSITORY,
    )
    receipt = executor.execute(
        _assignment({"path": "docs/brain/evidence.md", "sha256": _sha(source)})
    )
    result = receipt.output["results"][0]
    assert result["language"] == "text"
    assert result["syntax"] == "not_applicable"
    assert result["utf8"] is True


def test_path_escape_protected_path_and_duplicate_are_rejected(tmp_path: Path):
    root = _workspace(tmp_path)
    executor = IsolatedWorkspaceStaticValidationExecutor(
        workspace_root=root,
        repository_name=REPOSITORY,
    )
    for path in ("../outside.py", ".git/HEAD", ".github/workflows/unsafe.yml"):
        with pytest.raises(PermissionError):
            executor.execute(_assignment({"path": path, "sha256": "0" * 64}))

    source = b"VALUE = 1\n"
    (root / "app" / "example.py").write_bytes(source)
    item = {"path": "app/example.py", "sha256": _sha(source)}
    with pytest.raises(ValueError, match="DUPLICATE_PATH"):
        executor.execute(_assignment(item, item))


def test_branch_marker_and_mutation_guards(tmp_path: Path):
    root = _workspace(tmp_path)
    source = b"VALUE = 1\n"
    (root / "app" / "example.py").write_bytes(source)
    executor = IsolatedWorkspaceStaticValidationExecutor(
        workspace_root=root,
        repository_name=REPOSITORY,
    )
    item = {"path": "app/example.py", "sha256": _sha(source)}

    with pytest.raises(PermissionError, match="REVISION_MISMATCH"):
        executor.execute(_assignment(item, branch="autonomy/other"))

    (root / ".calyx-isolated-workspace.json").unlink()
    with pytest.raises(PermissionError, match="MARKER_REQUIRED"):
        executor.execute(_assignment(item))

    assignment = _assignment(item)
    bad_inputs = {
        "job": {
            **assignment.inputs["job"],
            "mutating_intent": True,
        }
    }
    with pytest.raises(PermissionError, match="MUTATION_PROHIBITED"):
        executor.execute(
            GovernedAssignment(
                assignment_id=assignment.assignment_id,
                program_id=assignment.program_id,
                job_key=assignment.job_key,
                role_key=assignment.role_key,
                objective=assignment.objective,
                inputs=bad_inputs,
            )
        )


def test_registry_marks_static_validator_as_non_mutating_non_executing(tmp_path: Path):
    root = _workspace(tmp_path)
    registry = AuthoritativeExecutorRegistry(
        workspace_root=root,
        repository_name=REPOSITORY,
    )
    registered = registry.require_authoritative(STATIC_VALIDATION_ROLE)
    assert registered.authoritative is True
    assert registered.workspace_mutation is False
    assert registered.repository_code_execution is False
    assert registered.external_side_effects is False
