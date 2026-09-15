"""OpenAI Codex terminal worker with git worktree lifecycle management.

This worker creates an isolated git worktree for each task, dispatches to
the Codex execution transport, and removes the worktree when the lane
reaches a terminal state (completed or blocked).

Safety invariants:
- The worktree path is fully resolved to an absolute path before removal.
- The filesystem root (/) and the current user's home directory are never
  targeted for removal.
- Cleanup never uses wildcards, recursive targets, or relative paths.
- Cleanup failure is non-fatal: logged and recorded in the receipt without
  discarding the primary task result.

Transports are injected; deterministic tests use mock transports with no
subprocess, no HTTP, and no real API calls.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger(__name__)

WORKER_ID = "openai-codex-worktree-worker-v1"


# ---------------------------------------------------------------------------
# Safety helpers
# ---------------------------------------------------------------------------


def _resolve_safe_worktree_path(path: str | Path) -> Path | None:
    """Resolve and validate a worktree path for safe removal.

    Returns the resolved absolute Path when safe, None otherwise.
    Rejects:
    - Non-absolute or unresolvable paths
    - The filesystem root (/)
    - The current user's home directory
    """
    try:
        p = Path(path).resolve()
    except Exception:  # noqa: BLE001
        return None
    if not p.is_absolute():
        return None
    if p == Path("/"):
        return None
    try:
        home = Path.home().resolve()
        if p == home:
            return None
    except Exception:  # noqa: BLE001
        log.debug("Could not determine home directory during worktree path check")
    return p


# ---------------------------------------------------------------------------
# Worktree transport protocol (injectable)
# ---------------------------------------------------------------------------


@runtime_checkable
class WorktreeTransport(Protocol):
    """Injectable transport for git worktree operations."""

    def add(self, repo_root: Path, worktree_path: Path, base_ref: str) -> None:
        """Create a git worktree at worktree_path checked out at base_ref."""
        ...  # pragma: no cover

    def remove(self, repo_root: Path, worktree_path: Path) -> None:
        """Remove the git worktree at worktree_path. Raises on failure."""
        ...  # pragma: no cover


class SubprocessWorktreeTransport:
    """Real git worktree transport backed by subprocess calls."""

    def add(self, repo_root: Path, worktree_path: Path, base_ref: str) -> None:
        result = subprocess.run(
            ["git", "worktree", "add", str(worktree_path), base_ref],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git worktree add failed (exit {result.returncode}): "
                f"{result.stderr.strip()}"
            )

    def remove(self, repo_root: Path, worktree_path: Path) -> None:
        result = subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree_path)],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git worktree remove failed (exit {result.returncode}): "
                f"{result.stderr.strip()}"
            )


# ---------------------------------------------------------------------------
# Execution transport protocol (injectable)
# ---------------------------------------------------------------------------


@runtime_checkable
class CodexExecutionTransport(Protocol):
    """Injectable transport for the Codex task execution step."""

    def execute(
        self, worktree_path: Path, task_key: str, objective: str
    ) -> dict[str, Any]:
        """Execute the task in the worktree.

        Returns a dict with at minimum a ``status`` key:
        ``"completed"`` for success, anything else for blocked/failure.
        A blocked result may include an ``"error_reason"`` key.
        """
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OpenAICodexWorkerReceipt:
    """Durable evidence record for one completed or blocked OpenAI Codex execution.

    worktree_path records the absolute path of the task worktree (or None
    if the worktree was never created).  worktree_cleanup_status records the
    outcome of the removal attempt:

    - ``"removed"``              -- worktree removed successfully
    - ``"not_created"``          -- worktree was never created (no removal needed)
    - ``"skipped:<reason>"``     -- removal skipped because the path is unsafe
    - ``"failed:<exc>:<detail>"``-- removal attempted but failed; exc is the
                                    exception class name
    """

    task_key: str
    worker_id: str
    status: str  # "completed" | "blocked"
    started_at: str
    completed_at: str
    duration_seconds: float
    worktree_path: str | None
    worktree_cleanup_status: str
    error_reason: str | None
    execution_result: dict[str, Any] | None = None

    def as_evidence(self) -> dict[str, Any]:
        return {
            "task_key": self.task_key,
            "worker_id": self.worker_id,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "worktree_path": self.worktree_path,
            "worktree_cleanup_status": self.worktree_cleanup_status,
            "error_reason": self.error_reason,
            "execution_result": self.execution_result,
        }


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class OpenAICodexWorker:
    """Terminal Codex worker with explicit git worktree lifecycle.

    For each task:

    1. Creates an isolated git worktree via *worktree_transport*.
    2. Executes the task in the worktree via *execution_transport*.
    3. On terminal exit (completed or blocked), removes the worktree and
       records ``worktree_path`` and ``worktree_cleanup_status`` in the receipt.
    4. Cleanup failure is non-fatal: logged and recorded in the receipt
       without discarding the primary task result.

    Inject a mock worktree transport and a mock execution transport to run
    deterministic proofs without any subprocess, HTTP, or real API calls.
    """

    def __init__(
        self,
        *,
        repo_root: str | Path,
        worktree_transport: WorktreeTransport,
        execution_transport: CodexExecutionTransport,
        worker_id: str = WORKER_ID,
        worktree_base_dir: str | Path | None = None,
    ) -> None:
        self._repo_root = Path(repo_root).resolve()
        self._worktree_transport = worktree_transport
        self._execution_transport = execution_transport
        self._worker_id = worker_id
        self._worktree_base_dir = (
            Path(worktree_base_dir).resolve()
            if worktree_base_dir is not None
            else Path(tempfile.gettempdir())
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def execute(
        self,
        task_key: str,
        *,
        objective: str = "",
        base_ref: str = "HEAD",
    ) -> OpenAICodexWorkerReceipt:
        """Execute one task with worktree isolation.

        Returns an :class:`OpenAICodexWorkerReceipt`; never raises.
        The BoundedDispatcher calls ``complete()`` or ``block()`` based on
        ``receipt.status``.
        """
        started = time.monotonic()
        started_at = datetime.now(timezone.utc).isoformat()
        worktree_path: Path | None = None

        # --- Create worktree ----------------------------------------
        try:
            worktree_path = self._build_worktree_path(task_key)
            self._worktree_transport.add(self._repo_root, worktree_path, base_ref)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Worktree creation failed for task %s: %s", task_key, exc
            )
            cleanup_status = self._cleanup(worktree_path)
            return self._receipt(
                task_key=task_key,
                status="blocked",
                started_at=started_at,
                elapsed=time.monotonic() - started,
                worktree_path=worktree_path,
                cleanup_status=cleanup_status,
                error_reason=f"WORKTREE_CREATE_FAILED:{exc}",
                execution_result=None,
            )

        # --- Execute task -------------------------------------------
        try:
            exec_result = self._execution_transport.execute(
                worktree_path, task_key, objective
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Codex execution failed for task %s: %s", task_key, exc
            )
            cleanup_status = self._cleanup(worktree_path)
            return self._receipt(
                task_key=task_key,
                status="blocked",
                started_at=started_at,
                elapsed=time.monotonic() - started,
                worktree_path=worktree_path,
                cleanup_status=cleanup_status,
                error_reason=f"CODEX_EXECUTION_FAILED:{exc}",
                execution_result=None,
            )

        # --- Terminal: cleanup and return receipt -------------------
        task_status = (
            "completed" if exec_result.get("status") == "completed" else "blocked"
        )
        error_reason: str | None = exec_result.get("error_reason")
        cleanup_status = self._cleanup(worktree_path)

        return self._receipt(
            task_key=task_key,
            status=task_status,
            started_at=started_at,
            elapsed=time.monotonic() - started,
            worktree_path=worktree_path,
            cleanup_status=cleanup_status,
            error_reason=error_reason,
            execution_result=exec_result,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_worktree_path(self, task_key: str) -> Path:
        """Return a unique, absolute path for the task worktree."""
        safe_key = "".join(
            c if (c.isalnum() or c in "-_") else "_" for c in task_key
        )[:32]
        ts = str(int(time.monotonic() * 1_000_000))[-10:]
        return self._worktree_base_dir / f"calyx-codex-{safe_key}-{ts}"

    def _cleanup(self, worktree_path: Path | None) -> str:
        """Remove the worktree. Returns a cleanup-status string; never raises."""
        if worktree_path is None:
            return "not_created"

        safe_path = _resolve_safe_worktree_path(worktree_path)
        if safe_path is None:
            log.error(
                "Worktree cleanup skipped: path %r is unsafe or unresolvable",
                str(worktree_path),
            )
            return f"skipped:unsafe_path:{worktree_path}"

        try:
            self._worktree_transport.remove(self._repo_root, safe_path)
            log.info("Worktree removed: %s", safe_path)
            return "removed"
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Worktree cleanup failed for %s: %s", safe_path, exc
            )
            return f"failed:{type(exc).__name__}:{exc}"

    def _receipt(
        self,
        *,
        task_key: str,
        status: str,
        started_at: str,
        elapsed: float,
        worktree_path: Path | None,
        cleanup_status: str,
        error_reason: str | None,
        execution_result: dict[str, Any] | None,
    ) -> OpenAICodexWorkerReceipt:
        return OpenAICodexWorkerReceipt(
            task_key=task_key,
            worker_id=self._worker_id,
            status=status,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc).isoformat(),
            duration_seconds=max(0.0, elapsed),
            worktree_path=str(worktree_path) if worktree_path is not None else None,
            worktree_cleanup_status=cleanup_status,
            error_reason=error_reason,
            execution_result=execution_result,
        )
