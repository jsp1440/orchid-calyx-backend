from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.calyx_orchestrator.executor import ExecutionState, GovernedAssignment
from app.calyx_orchestrator.executor_registry import AuthoritativeExecutorRegistry
from app.calyx_orchestrator.isolated_patch_executor import (
    ABSENT_PREIMAGE,
    ISOLATED_PATCH_ROLE,
    IsolatedWorkspacePatchExecutor,
)

REPOSITORY = "jsp1440/orchid-calyx-backend"
BRANCH = "autonomy/test-patch"
COMMIT = "a" * 40


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "worktree"
    (root / ".git" / "refs" / "heads" / "autonomy").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text(f"ref: refs/heads/{BRANCH}\n", encoding="ascii")
    (root / ".git" / "refs" / "heads" / "autonomy" / "test-patch").write_text(
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


def _assignment(*patches: dict, branch: str = BRANCH, capabilities: tuple[str, ...] = ("workspace_write",)) -> GovernedAssignment:
    return GovernedAssignment(
        assignment_id="assignment-114c",
        program_id="program-114c",
        job_key="job-114c",
        role_key=ISOLATED_PATCH_ROLE,
        objective="Apply a bounded isolated workspace patch",
        inputs={
            "job": {
                "repository": REPOSITORY,
                "branch": branch,
                "mutating_intent": True,
                "patches": list(patches),
            }
        },
        requested_capabilities=capabilities,
        evidence_uris=("brain-build:BUILD-BRAIN-114C",),
    )


def test_replaces_existing_file_and_emits_hash_bound_receipt(tmp_path: Path):
    root = _workspace(tmp_path)
    target = root / "app" / "example.py"
    before = b"VALUE = 1\n"
    after = "VALUE = 2\n"
    target.write_bytes(before)

    executor = IsolatedWorkspacePatchExecutor(workspace_root=root, repository_name=REPOSITORY)
    receipt = executor.execute(
        _assignment(
            {
                "path": "app/example.py",
                "before_sha256": _sha(before),
                "content_utf8": after,
            }
        )
    )

    assert target.read_text(encoding="utf-8") == after
    assert receipt.state == ExecutionState.DELIVERED
    assert receipt.output["commit_created"] is False
    assert receipt.output["validation_commands_run"] is False
    assert receipt.output["changes"][0]["before_sha256"] == _sha(before)
    assert receipt.output["changes"][0]["after_sha256"] == _sha(after.encode())
    receipt.verify()


def test_creates_new_allowlisted_file_only_with_absent_preimage(tmp_path: Path):
    root = _workspace(tmp_path)
    executor = IsolatedWorkspacePatchExecutor(workspace_root=root, repository_name=REPOSITORY)
    receipt = executor.execute(
        _assignment(
            {
                "path": "tests/test_generated.py",
                "before_sha256": ABSENT_PREIMAGE,
                "content_utf8": "def test_generated():\n    assert True\n",
            }
        )
    )
    assert (root / "tests" / "test_generated.py").is_file()
    assert receipt.output["changes"][0]["created"] is True


def test_stale_preimage_rejected_without_mutation(tmp_path: Path):
    root = _workspace(tmp_path)
    first = root / "app" / "first.py"
    second = root / "app" / "second.py"
    first.write_text("FIRST = 1\n", encoding="utf-8")
    second.write_text("SECOND = 1\n", encoding="utf-8")
    executor = IsolatedWorkspacePatchExecutor(workspace_root=root, repository_name=REPOSITORY)

    with pytest.raises(ValueError, match="PREIMAGE_MISMATCH"):
        executor.execute(
            _assignment(
                {
                    "path": "app/first.py",
                    "before_sha256": _sha(first.read_bytes()),
                    "content_utf8": "FIRST = 2\n",
                },
                {
                    "path": "app/second.py",
                    "before_sha256": "0" * 64,
                    "content_utf8": "SECOND = 2\n",
                },
            )
        )

    assert first.read_text(encoding="utf-8") == "FIRST = 1\n"
    assert second.read_text(encoding="utf-8") == "SECOND = 1\n"


def test_protected_path_and_path_escape_are_rejected(tmp_path: Path):
    root = _workspace(tmp_path)
    executor = IsolatedWorkspacePatchExecutor(workspace_root=root, repository_name=REPOSITORY)
    for path in (".github/workflows/danger.yml", "../outside.py", ".git/HEAD"):
        with pytest.raises(PermissionError):
            executor.execute(
                _assignment(
                    {
                        "path": path,
                        "before_sha256": ABSENT_PREIMAGE,
                        "content_utf8": "blocked\n",
                    }
                )
            )


def test_branch_mismatch_and_missing_marker_fail_closed(tmp_path: Path):
    root = _workspace(tmp_path)
    executor = IsolatedWorkspacePatchExecutor(workspace_root=root, repository_name=REPOSITORY)
    with pytest.raises(PermissionError, match="REVISION_MISMATCH"):
        executor.execute(
            _assignment(
                {
                    "path": "app/example.py",
                    "before_sha256": ABSENT_PREIMAGE,
                    "content_utf8": "x = 1\n",
                },
                branch="autonomy/other",
            )
        )

    (root / ".calyx-isolated-workspace.json").unlink()
    with pytest.raises(PermissionError, match="MARKER_REQUIRED"):
        executor.execute(
            _assignment(
                {
                    "path": "app/example.py",
                    "before_sha256": ABSENT_PREIMAGE,
                    "content_utf8": "x = 1\n",
                }
            )
        )


def test_symlink_target_is_rejected(tmp_path: Path):
    root = _workspace(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("OUTSIDE = 1\n", encoding="utf-8")
    link = root / "app" / "linked.py"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")

    executor = IsolatedWorkspacePatchExecutor(workspace_root=root, repository_name=REPOSITORY)
    with pytest.raises(PermissionError):
        executor.execute(
            _assignment(
                {
                    "path": "app/linked.py",
                    "before_sha256": _sha(outside.read_bytes()),
                    "content_utf8": "OUTSIDE = 2\n",
                }
            )
        )
    assert outside.read_text(encoding="utf-8") == "OUTSIDE = 1\n"


def test_prohibited_capability_and_non_autonomy_branch_are_rejected(tmp_path: Path):
    root = _workspace(tmp_path)
    executor = IsolatedWorkspacePatchExecutor(workspace_root=root, repository_name=REPOSITORY)
    patch = {
        "path": "app/example.py",
        "before_sha256": ABSENT_PREIMAGE,
        "content_utf8": "x = 1\n",
    }
    with pytest.raises(PermissionError, match="PROHIBITED_CAPABILITY"):
        executor.execute(_assignment(patch, capabilities=("workspace_write", "shell")))

    with pytest.raises(PermissionError, match="AUTONOMY_BRANCH_REQUIRED"):
        executor.execute(_assignment(patch, branch="main"))


def test_registry_exposes_mutation_boundary(tmp_path: Path):
    root = _workspace(tmp_path)
    registry = AuthoritativeExecutorRegistry(workspace_root=root, repository_name=REPOSITORY)
    registered = registry.require_authoritative(ISOLATED_PATCH_ROLE)
    assert registered.authoritative is True
    assert registered.external_side_effects is False
    assert registered.workspace_mutation is True
    status = registry.status()
    entry = next(item for item in status["executors"] if item["role_key"] == ISOLATED_PATCH_ROLE)
    assert entry["workspace_mutation"] is True
