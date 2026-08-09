from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.calyx_orchestrator.executor import GovernedAssignment
from app.calyx_orchestrator.isolated_patch_executor import (
    ABSENT_PREIMAGE,
    ISOLATED_PATCH_ROLE,
    ROLLBACK_JOURNAL_PREFIX,
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
    (root / ".git" / "HEAD").write_text(f"ref: refs/heads/{BRANCH}\n", encoding="ascii")
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


def _executor(root: Path) -> IsolatedWorkspacePatchExecutor:
    return IsolatedWorkspacePatchExecutor(
        workspace_root=root,
        repository_name=REPOSITORY,
    )


def _journals(root: Path) -> list[Path]:
    return list(root.glob(f"{ROLLBACK_JOURNAL_PREFIX}*.json"))


def test_rollback_restores_existing_file_and_removes_created_file(tmp_path: Path):
    root = _workspace(tmp_path)
    existing = root / "app" / "existing.py"
    created = root / "tests" / "created.py"
    before = b"VALUE = 1\n"
    existing.write_bytes(before)
    executor = _executor(root)

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
    assert len(_journals(root)) == 1

    assert executor.rollback(receipt.assignment_id) is True
    assert existing.read_bytes() == before
    assert not created.exists()
    assert _journals(root) == []
    assert executor.rollback(receipt.assignment_id) is False


def test_finalize_discards_preimage_only_after_successful_completion(tmp_path: Path):
    root = _workspace(tmp_path)
    target = root / "app" / "example.py"
    before = b"VALUE = 1\n"
    target.write_bytes(before)
    executor = _executor(root)

    receipt = executor.execute(
        _assignment(
            {
                "path": "app/example.py",
                "before_sha256": _sha(before),
                "content_utf8": "VALUE = 2\n",
            }
        )
    )
    assert len(_journals(root)) == 1
    executor.finalize(receipt.assignment_id)

    assert target.read_text(encoding="utf-8") == "VALUE = 2\n"
    assert _journals(root) == []
    assert executor.rollback(receipt.assignment_id) is False


def test_new_executor_recovers_crashed_assignment_before_retry(tmp_path: Path):
    root = _workspace(tmp_path)
    existing = root / "app" / "existing.py"
    created = root / "tests" / "created.py"
    before = b"VALUE = 1\n"
    existing.write_bytes(before)
    assignment = _assignment(
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

    first_process = _executor(root)
    first_process.execute(assignment)
    assert existing.read_text(encoding="utf-8") == "VALUE = 2\n"
    assert created.exists()
    assert len(_journals(root)) == 1

    second_process = _executor(root)
    retry = second_process.execute(assignment)

    assert retry.state.value == "delivered"
    assert existing.read_text(encoding="utf-8") == "VALUE = 2\n"
    assert created.exists()
    assert len(_journals(root)) == 1
    second_process.rollback(assignment.assignment_id)
    assert existing.read_bytes() == before
    assert not created.exists()


def test_crash_recovery_fails_closed_if_workspace_diverged(tmp_path: Path):
    root = _workspace(tmp_path)
    target = root / "app" / "example.py"
    before = b"VALUE = 1\n"
    target.write_bytes(before)
    assignment = _assignment(
        {
            "path": "app/example.py",
            "before_sha256": _sha(before),
            "content_utf8": "VALUE = 2\n",
        }
    )
    _executor(root).execute(assignment)
    target.write_text("THIRD_PARTY = True\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="ISOLATED_PATCH_ROLLBACK_STATE_DIVERGED"):
        _executor(root).execute(assignment)

    assert target.read_text(encoding="utf-8") == "THIRD_PARTY = True\n"
    assert len(_journals(root)) == 1


def test_tampered_journal_is_rejected_without_touching_workspace(tmp_path: Path):
    root = _workspace(tmp_path)
    target = root / "app" / "example.py"
    before = b"VALUE = 1\n"
    target.write_bytes(before)
    assignment = _assignment(
        {
            "path": "app/example.py",
            "before_sha256": _sha(before),
            "content_utf8": "VALUE = 2\n",
        }
    )
    _executor(root).execute(assignment)
    journal = _journals(root)[0]
    payload = json.loads(journal.read_text(encoding="utf-8"))
    payload["entries"][0]["before_sha256"] = "0" * 64
    journal.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        RuntimeError, match="ISOLATED_PATCH_ROLLBACK_JOURNAL_CHECKSUM_MISMATCH"
    ):
        _executor(root).execute(assignment)

    assert target.read_text(encoding="utf-8") == "VALUE = 2\n"
