from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.calyx_orchestrator.executor import GovernedAssignment
from app.calyx_orchestrator.isolated_patch_executor import (
    ABSENT_PREIMAGE,
    ISOLATED_PATCH_ROLE,
    IsolatedWorkspacePatchExecutor,
)

REPOSITORY = "jsp1440/orchid-calyx-backend"
BRANCH = "autonomy/rollback-test"
COMMIT = "b" * 40


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "worktree"
    (root / ".git" / "refs" / "heads" / "autonomy").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text(
        f"ref: refs/heads/{BRANCH}\n", encoding="ascii"
    )
    (root / ".git" / "refs" / "heads" / "autonomy" / "rollback-test").write_text(
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
            }
        ),
        encoding="utf-8",
    )
    return root


def _assignment(*patches: dict[str, object]) -> GovernedAssignment:
    return GovernedAssignment(
        assignment_id="assignment-rollback-114m",
        program_id="program-rollback-114m",
        job_key="job-rollback-114m",
        role_key=ISOLATED_PATCH_ROLE,
        objective="Prove recoverable workspace mutation",
        inputs={
            "job": {
                "repository": REPOSITORY,
                "branch": BRANCH,
                "mutating_intent": True,
                "patches": list(patches),
            }
        },
        requested_capabilities=("workspace_write",),
    )


def test_rollback_restores_existing_file_and_removes_created_file(tmp_path: Path):
    root = _workspace(tmp_path)
    existing = root / "app" / "existing.py"
    created = root / "tests" / "created.py"
    before = b"VALUE = 1\n"
    existing.write_bytes(before)
    executor = IsolatedWorkspacePatchExecutor(
        workspace_root=root,
        repository_name=REPOSITORY,
    )

    receipt = executor.execute(
        _assignment(
            {
                "path": "app/existing.py",
                "before_sha256": _sha(before),
                "content_utf8": "VALUE = 2\n",
            },
            {
                "path": "tests/created.py",
                "before_sha256": ABSENT_PREIMAGE,
                "content_utf8": "CREATED = True\n",
            },
        )
    )
    assert existing.read_text(encoding="utf-8") == "VALUE = 2\n"
    assert created.exists()

    assert executor.rollback(receipt.assignment_id) is True
    assert existing.read_bytes() == before
    assert not created.exists()
    assert executor.rollback(receipt.assignment_id) is False


def test_finalize_discards_preimage_only_after_successful_completion(tmp_path: Path):
    root = _workspace(tmp_path)
    target = root / "app" / "example.py"
    before = b"VALUE = 1\n"
    target.write_bytes(before)
    executor = IsolatedWorkspacePatchExecutor(
        workspace_root=root,
        repository_name=REPOSITORY,
    )

    receipt = executor.execute(
        _assignment(
            {
                "path": "app/example.py",
                "before_sha256": _sha(before),
                "content_utf8": "VALUE = 2\n",
            }
        )
    )
    executor.finalize(receipt.assignment_id)

    assert target.read_text(encoding="utf-8") == "VALUE = 2\n"
    assert executor.rollback(receipt.assignment_id) is False
