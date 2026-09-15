"""Tests for OpenAI Codex terminal worker worktree lifecycle.

Covers:
- Success path: worktree created, task completes, worktree removed.
- Blocked path (bad exec result): worktree still removed on terminal exit.
- Blocked path (execution exception): worktree still removed.
- Worktree creation failure: receipt records blocked and cleanup attempted.
- Cleanup failure: recorded in receipt without discarding the primary task result.
- Safety: filesystem root and home directory paths are rejected.
- Receipt fields: worktree_path and worktree_cleanup_status always present.
- as_evidence() serialisation round-trip.
- No subprocess, no HTTP, no real API call in any test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.calyx_orchestrator.openai_codex_worker import (
    WORKER_ID,
    OpenAICodexWorker,
    OpenAICodexWorkerReceipt,
    _resolve_safe_worktree_path,
)

# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------


def _mock_worktree_transport(*, remove_raises: Exception | None = None) -> MagicMock:
    """Return a mock WorktreeTransport. ``remove`` raises if specified."""
    transport = MagicMock()
    transport.add.return_value = None
    if remove_raises is not None:
        transport.remove.side_effect = remove_raises
    else:
        transport.remove.return_value = None
    return transport


def _mock_exec_transport(*, result: dict[str, Any]) -> MagicMock:
    """Return a mock CodexExecutionTransport with a fixed execute() result."""
    transport = MagicMock()
    transport.execute.return_value = result
    return transport


def _mock_exec_transport_raises(*, exc: Exception) -> MagicMock:
    """Return a mock CodexExecutionTransport whose execute() raises."""
    transport = MagicMock()
    transport.execute.side_effect = exc
    return transport


def _make_worker(
    *,
    worktree_transport: MagicMock | None = None,
    execution_transport: MagicMock | None = None,
    repo_root: Path | None = None,
    worktree_base_dir: Path | None = None,
    tmp_path: Path | None = None,
) -> OpenAICodexWorker:
    _repo = repo_root or (tmp_path / "repo" if tmp_path else Path("/repo"))
    _base = worktree_base_dir or (tmp_path / "worktrees" if tmp_path else Path("/tmp"))
    return OpenAICodexWorker(
        repo_root=_repo,
        worktree_transport=worktree_transport or _mock_worktree_transport(),
        execution_transport=execution_transport
        or _mock_exec_transport(result={"status": "completed"}),
        worktree_base_dir=_base,
    )


# ---------------------------------------------------------------------------
# _resolve_safe_worktree_path -- safety gate unit tests
# ---------------------------------------------------------------------------


class TestResolveSafeWorktreePath:
    def test_absolute_path_returned(self, tmp_path: Path) -> None:
        result = _resolve_safe_worktree_path(tmp_path / "worktree-abc")
        assert result is not None
        assert result.is_absolute()

    def test_root_rejected(self) -> None:
        assert _resolve_safe_worktree_path(Path("/")) is None

    def test_home_directory_rejected(self) -> None:
        home = Path.home()
        assert _resolve_safe_worktree_path(home) is None

    def test_path_inside_home_is_allowed(self) -> None:
        # A subdirectory of home must NOT be rejected (only home itself).
        inside_home = Path.home() / "some-worktree-subdir-that-does-not-exist"
        result = _resolve_safe_worktree_path(inside_home)
        assert result is not None

    def test_deep_absolute_path_allowed(self) -> None:
        result = _resolve_safe_worktree_path("/tmp/calyx-codex-task1-12345")
        assert result is not None
        assert result == Path("/tmp/calyx-codex-task1-12345")

    def test_string_path_accepted(self) -> None:
        result = _resolve_safe_worktree_path("/tmp/calyx-worktree-xyz")
        assert result is not None


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


class TestSuccessPath:
    def test_receipt_status_completed(self, tmp_path: Path) -> None:
        wt = _mock_worktree_transport()
        ex = _mock_exec_transport(result={"status": "completed"})
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-success-1", objective="add feature X")

        assert receipt.status == "completed"

    def test_worktree_remove_called_on_success(self, tmp_path: Path) -> None:
        wt = _mock_worktree_transport()
        ex = _mock_exec_transport(result={"status": "completed"})
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        worker.execute("task-success-2")

        assert wt.remove.call_count == 1
        _repo_arg, wt_path_arg = wt.remove.call_args.args
        assert isinstance(wt_path_arg, Path)
        assert wt_path_arg.is_absolute()

    def test_cleanup_status_removed_on_success(self, tmp_path: Path) -> None:
        wt = _mock_worktree_transport()
        ex = _mock_exec_transport(result={"status": "completed"})
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-success-3")

        assert receipt.worktree_cleanup_status == "removed"

    def test_worktree_path_recorded_in_receipt(self, tmp_path: Path) -> None:
        wt = _mock_worktree_transport()
        ex = _mock_exec_transport(result={"status": "completed"})
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-success-4")

        assert receipt.worktree_path is not None
        assert Path(receipt.worktree_path).is_absolute()

    def test_receipt_has_correct_worker_id(self, tmp_path: Path) -> None:
        wt = _mock_worktree_transport()
        ex = _mock_exec_transport(result={"status": "completed"})
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-id-check")

        assert receipt.worker_id == WORKER_ID

    def test_receipt_duration_non_negative(self, tmp_path: Path) -> None:
        wt = _mock_worktree_transport()
        ex = _mock_exec_transport(result={"status": "completed"})
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-dur")

        assert receipt.duration_seconds >= 0.0


# ---------------------------------------------------------------------------
# Blocked path -- bad execution result (not "completed")
# ---------------------------------------------------------------------------


class TestBlockedPathBadResult:
    def test_receipt_status_blocked_when_exec_returns_blocked(
        self, tmp_path: Path
    ) -> None:
        wt = _mock_worktree_transport()
        ex = _mock_exec_transport(
            result={"status": "blocked", "error_reason": "SOME_REASON"}
        )
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-blocked-1")

        assert receipt.status == "blocked"
        assert receipt.error_reason == "SOME_REASON"

    def test_worktree_removed_on_blocked_result(self, tmp_path: Path) -> None:
        wt = _mock_worktree_transport()
        ex = _mock_exec_transport(result={"status": "blocked"})
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-blocked-2")

        assert wt.remove.call_count == 1
        assert receipt.worktree_cleanup_status == "removed"

    def test_worktree_path_recorded_on_blocked_result(self, tmp_path: Path) -> None:
        wt = _mock_worktree_transport()
        ex = _mock_exec_transport(result={"status": "blocked"})
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-blocked-path")

        assert receipt.worktree_path is not None


# ---------------------------------------------------------------------------
# Blocked path -- execution transport raises
# ---------------------------------------------------------------------------


class TestBlockedPathExecException:
    def test_receipt_status_blocked_on_exec_exception(self, tmp_path: Path) -> None:
        wt = _mock_worktree_transport()
        ex = _mock_exec_transport_raises(exc=RuntimeError("CLI failed"))
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-exc-1")

        assert receipt.status == "blocked"

    def test_worktree_removed_on_exec_exception(self, tmp_path: Path) -> None:
        wt = _mock_worktree_transport()
        ex = _mock_exec_transport_raises(exc=RuntimeError("CLI failed"))
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-exc-2")

        assert wt.remove.call_count == 1
        assert receipt.worktree_cleanup_status == "removed"

    def test_error_reason_records_exception_on_exec_failure(
        self, tmp_path: Path
    ) -> None:
        wt = _mock_worktree_transport()
        ex = _mock_exec_transport_raises(exc=RuntimeError("CLI failed"))
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-exc-3")

        assert receipt.error_reason is not None
        assert "CODEX_EXECUTION_FAILED" in receipt.error_reason

    def test_worker_never_raises(self, tmp_path: Path) -> None:
        wt = _mock_worktree_transport()
        ex = _mock_exec_transport_raises(exc=ValueError("unexpected"))
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-no-raise")
        assert isinstance(receipt, OpenAICodexWorkerReceipt)


# ---------------------------------------------------------------------------
# Worktree creation failure
# ---------------------------------------------------------------------------


class TestWorktreeCreationFailure:
    def test_receipt_blocked_when_add_raises(self, tmp_path: Path) -> None:
        wt = _mock_worktree_transport()
        wt.add.side_effect = RuntimeError("no disk space")
        ex = _mock_exec_transport(result={"status": "completed"})
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-add-fail")

        assert receipt.status == "blocked"
        assert "WORKTREE_CREATE_FAILED" in (receipt.error_reason or "")

    def test_exec_not_called_when_add_raises(self, tmp_path: Path) -> None:
        wt = _mock_worktree_transport()
        wt.add.side_effect = RuntimeError("no disk space")
        ex = _mock_exec_transport(result={"status": "completed"})
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        worker.execute("task-add-fail-no-exec")

        ex.execute.assert_not_called()

    def test_cleanup_attempted_when_add_raises(self, tmp_path: Path) -> None:
        """Cleanup is attempted even after add() fails (path was already built)."""
        wt = _mock_worktree_transport()
        wt.add.side_effect = RuntimeError("mount error")
        ex = _mock_exec_transport(result={"status": "completed"})
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-add-fail-cleanup")

        # remove was attempted; mock returns None so status is "removed"
        assert wt.remove.call_count == 1
        assert receipt.worktree_cleanup_status == "removed"


# ---------------------------------------------------------------------------
# Cleanup failure -- primary result preserved
# ---------------------------------------------------------------------------


class TestCleanupFailure:
    def test_cleanup_failure_does_not_change_status_on_success(
        self, tmp_path: Path
    ) -> None:
        wt = _mock_worktree_transport(remove_raises=OSError("permission denied"))
        ex = _mock_exec_transport(result={"status": "completed"})
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-cleanup-fail-success")

        # Primary status must be preserved.
        assert receipt.status == "completed"

    def test_cleanup_failure_recorded_in_receipt(self, tmp_path: Path) -> None:
        wt = _mock_worktree_transport(remove_raises=OSError("permission denied"))
        ex = _mock_exec_transport(result={"status": "completed"})
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-cleanup-fail-record")

        assert receipt.worktree_cleanup_status.startswith("failed:")

    def test_cleanup_failure_does_not_change_status_on_blocked(
        self, tmp_path: Path
    ) -> None:
        wt = _mock_worktree_transport(remove_raises=RuntimeError("worktree busy"))
        ex = _mock_exec_transport(result={"status": "blocked"})
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-cleanup-fail-blocked")

        assert receipt.status == "blocked"
        assert receipt.worktree_cleanup_status.startswith("failed:")

    def test_worker_never_raises_on_cleanup_failure(self, tmp_path: Path) -> None:
        wt = _mock_worktree_transport(remove_raises=Exception("catastrophic"))
        ex = _mock_exec_transport(result={"status": "completed"})
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-no-raise-cleanup")
        assert isinstance(receipt, OpenAICodexWorkerReceipt)

    def test_cleanup_failure_exc_class_in_status(self, tmp_path: Path) -> None:
        wt = _mock_worktree_transport(remove_raises=FileNotFoundError("gone"))
        ex = _mock_exec_transport(result={"status": "completed"})
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-exc-class")

        assert "FileNotFoundError" in receipt.worktree_cleanup_status


# ---------------------------------------------------------------------------
# Exact worktree path safety -- remove only the task worktree
# ---------------------------------------------------------------------------


class TestWorktreePathSafety:
    def test_remove_called_with_exact_task_worktree_path(
        self, tmp_path: Path
    ) -> None:
        wt = _mock_worktree_transport()
        ex = _mock_exec_transport(result={"status": "completed"})
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-exact-path")

        remove_args = wt.remove.call_args.args
        removed_path = remove_args[1]
        assert str(removed_path) == receipt.worktree_path

    def test_add_called_with_exact_task_worktree_path(
        self, tmp_path: Path
    ) -> None:
        wt = _mock_worktree_transport()
        ex = _mock_exec_transport(result={"status": "completed"})
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-add-path")

        add_args = wt.add.call_args.args
        added_path = add_args[1]
        assert str(added_path) == receipt.worktree_path

    def test_worktree_path_under_base_dir(self, tmp_path: Path) -> None:
        base = tmp_path / "worktrees"
        base.mkdir()
        wt = _mock_worktree_transport()
        ex = _mock_exec_transport(result={"status": "completed"})
        worker = _make_worker(
            worktree_transport=wt,
            execution_transport=ex,
            tmp_path=tmp_path,
            worktree_base_dir=base,
        )

        receipt = worker.execute("task-base-dir")

        assert receipt.worktree_path is not None
        assert Path(receipt.worktree_path).parent.resolve() == base.resolve()


# ---------------------------------------------------------------------------
# Receipt serialisation
# ---------------------------------------------------------------------------


class TestReceiptSerialisation:
    def test_as_evidence_contains_required_keys(self, tmp_path: Path) -> None:
        wt = _mock_worktree_transport()
        ex = _mock_exec_transport(result={"status": "completed"})
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-ser-1")
        evidence = receipt.as_evidence()

        required_keys = {
            "task_key",
            "worker_id",
            "status",
            "started_at",
            "completed_at",
            "duration_seconds",
            "worktree_path",
            "worktree_cleanup_status",
            "error_reason",
        }
        assert required_keys.issubset(evidence.keys())

    def test_as_evidence_worktree_path_matches_receipt(self, tmp_path: Path) -> None:
        wt = _mock_worktree_transport()
        ex = _mock_exec_transport(result={"status": "completed"})
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("task-ser-2")
        evidence = receipt.as_evidence()

        assert evidence["worktree_path"] == receipt.worktree_path
        assert evidence["worktree_cleanup_status"] == receipt.worktree_cleanup_status

    def test_as_evidence_task_key_matches(self, tmp_path: Path) -> None:
        wt = _mock_worktree_transport()
        ex = _mock_exec_transport(result={"status": "completed"})
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)

        receipt = worker.execute("my-unique-task-key")
        evidence = receipt.as_evidence()

        assert evidence["task_key"] == "my-unique-task-key"


# ---------------------------------------------------------------------------
# No subprocess / no API proof
# ---------------------------------------------------------------------------


class TestNoSubprocessNoAPI:
    def test_zero_subprocess_calls_in_mock_tests(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guard: SubprocessWorktreeTransport is never instantiated in tests."""
        import subprocess as sp

        original_run = sp.run
        calls: list[Any] = []

        def capturing_run(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
            calls.append(args)
            return original_run(*args, **kwargs)

        monkeypatch.setattr(sp, "run", capturing_run)

        wt = _mock_worktree_transport()
        ex = _mock_exec_transport(result={"status": "completed"})
        worker = _make_worker(worktree_transport=wt, execution_transport=ex, tmp_path=tmp_path)
        worker.execute("task-no-subprocess")

        assert calls == [], f"Unexpected subprocess.run calls: {calls}"
