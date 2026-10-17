"""Opt-in refresh of the worker's read-only workspace clone (P1 discovery).

Governed work sources (``calyx_brain.work_sources``) discover work from the
worker's workspace checkout. That checkout is cloned once at container start,
so without a refresh newly committed work (for example a new
``data/traitbank/*.json`` batch) is never seen and the scheduler idles
forever with nothing to do.

The refresh is deliberately narrow:

* off unless ``OC_BRAIN_WORKSPACE_REFRESH_SECONDS`` is set;
* follows one named remote branch, validated against a strict pattern;
* runs only when the Brain ledger has no work in flight, so no submitted job
  can see its pinned files change underneath it;
* skips a workspace with modified tracked files (untracked files, such as the
  isolation marker, are kept);
* never raises: every attempt is reported in the cycle receipt.
"""

from __future__ import annotations

import re
import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

REF_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")
GIT_TIMEOUT_SECONDS = 120


class WorkspaceRefresher:
    def __init__(
        self,
        workspace: Path,
        ref: str,
        interval_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        if not REF_PATTERN.fullmatch(ref) or ".." in ref:
            raise ValueError("OC_BRAIN_WORKSPACE_REFRESH_REF_INVALID")
        if interval_seconds <= 0:
            raise ValueError("OC_BRAIN_WORKSPACE_REFRESH_SECONDS_OUT_OF_RANGE")
        self.workspace = workspace
        self.ref = ref
        self.interval_seconds = interval_seconds
        self._clock = clock
        self._run = run
        self._last_attempt: float | None = None

    def _git(self, *args: str) -> str:
        completed = self._run(
            ["git", "-C", str(self.workspace), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
        return completed.stdout.strip()

    def refresh(self, ledger_state: Mapping[str, Any] | None) -> dict[str, Any]:
        moment = self._clock()
        if (
            self._last_attempt is not None
            and moment - self._last_attempt < self.interval_seconds
        ):
            return {"status": "not_due"}
        work = (ledger_state or {}).get("work") or {}
        in_flight = sum(
            1 for record in work.values() if (record or {}).get("state") == "in_flight"
        )
        if in_flight:
            # Retried on the next cycle; the interval does not restart.
            return {"status": "deferred_in_flight", "in_flight": in_flight}
        self._last_attempt = moment
        try:
            if self._git("status", "--porcelain", "--untracked-files=no"):
                return {"status": "skipped_dirty"}
            before = self._git("rev-parse", "HEAD")
            self._git("fetch", "-q", "--depth", "1", "origin", self.ref)
            after = self._git("rev-parse", "FETCH_HEAD")
            if after == before:
                return {"status": "current", "commit": before}
            self._git("reset", "-q", "--hard", "FETCH_HEAD")
            return {"status": "updated", "from": before, "to": after}
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "").strip().splitlines()[-1:] or [
                str(exc.returncode)
            ]
            return {"status": "failed", "detail": f"GIT_FAILED:{detail[0][:160]}"}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"status": "failed", "detail": type(exc).__name__}


def refresher_from_env(
    env: Mapping[str, str], *, workspace: str
) -> WorkspaceRefresher | None:
    raw = str(env.get("OC_BRAIN_WORKSPACE_REFRESH_SECONDS", "")).strip()
    if not raw or raw == "0":
        return None
    try:
        seconds = int(raw)
    except ValueError as exc:
        raise ValueError("OC_BRAIN_WORKSPACE_REFRESH_SECONDS_INVALID") from exc
    if not 60 <= seconds <= 86400:
        raise ValueError("OC_BRAIN_WORKSPACE_REFRESH_SECONDS_OUT_OF_RANGE")
    if not workspace:
        raise ValueError("OC_BRAIN_WORKSPACE_REFRESH_REQUIRES_WORKSPACE")
    ref = str(env.get("OC_BRAIN_WORKSPACE_REFRESH_REF", "")).strip()
    if not ref:
        raise ValueError("OC_BRAIN_WORKSPACE_REFRESH_REF_REQUIRED")
    return WorkspaceRefresher(Path(workspace), ref, seconds)
