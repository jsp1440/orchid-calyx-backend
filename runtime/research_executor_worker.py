"""Worker binding for the BUILD-051 research executor.

:mod:`runtime.research_executor` deliberately knows nothing about where
requests are stored or how a requester is told the answer. This module is the
one place those are chosen, so the executor stays testable and the wiring stays
inspectable.

Storage follows what the intake already does: the canonical
``oc_admin.build051_research_requests`` table when ``DATABASE_URL`` is
configured, and an in-process store otherwise. The fallback exists so a
developer machine can run the loop; it is not durable, and
:func:`store_persistence_mode` reports which one is live rather than letting a
caller assume.

Feedback reuses the bridge's own comment marker, which is keyed by request id.
Updating a request's status therefore edits the comment the intake already
posted instead of adding a second one — the deduplication is a property of the
marker, not of a check somebody has to remember to write.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

from runtime.research_executor import (
    BLOCKED,
    COMPLETED,
    ExecutionReport,
    MemoryRequestStore,
    PostgresRequestStore,
    RequestStore,
    ResearchExecutor,
    ResearchRunner,
)

#: Set by the deployment to turn the loop on. Absent means off, so a deploy
#: that has not been authorized to execute research does not start executing it.
WORKER_ENABLED_ENV = "CALYX_RESEARCH_EXECUTOR_ENABLED"


def worker_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    return str(source.get(WORKER_ENABLED_ENV, "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def store_persistence_mode(env: Mapping[str, str] | None = None) -> str:
    """``durable_database`` or ``in_process_memory`` — never a guess."""
    source = env if env is not None else os.environ
    return "durable_database" if str(source.get("DATABASE_URL", "")).strip() else "in_process_memory"


def build_request_store(
    *,
    env: Mapping[str, str] | None = None,
    db_execute: Callable[[Callable[[Any], Any]], Any] | None = None,
) -> RequestStore:
    """The store the intake already writes to, or the in-process fallback."""
    if store_persistence_mode(env) == "durable_database":
        if db_execute is None:
            from app.routers.owner_operations import db_execute as _db_execute

            db_execute = _db_execute
        return PostgresRequestStore(db_execute)

    from app.routers.owner_operations import MEMORY

    return MemoryRequestStore(MEMORY.get("research_requests", []))


def _status_comment(record: Mapping[str, Any]) -> tuple[str, str] | None:
    """The marker and body for a terminal request, or None when unreportable."""
    provenance = dict(record.get("provenance") or {})
    repository = str(provenance.get("source_repository") or "").strip()
    issue_number = provenance.get("source_issue_number")
    if not repository or not issue_number:
        return None

    request_id = str(record.get("id") or "")
    marker = f"<!-- calyx-research-bridge:{request_id} -->"
    state = str(record.get("status") or "")

    if state == COMPLETED:
        artifacts = ", ".join(str(item) for item in record.get("artifact_ids") or ())
        detail = f"Result artifacts: {artifacts}." if artifacts else ""
    elif state == BLOCKED:
        code = str(record.get("blocker_code") or "UNSPECIFIED")
        # The requester is told what stopped it and whether asking again could
        # change the answer. "Blocked" on its own invites a pointless retry.
        retryable = record.get("blocker_retryable")
        suffix = (
            " This may resolve on a retry."
            if retryable
            else " Re-running will not change this without new evidence."
        )
        detail = f"Blocker: `{code}` — {record.get('blocker') or 'no detail recorded'}.{suffix}"
    else:
        return None

    body = (
        f"{marker}\nCalyx research request **{request_id}** is now "
        f"**{state}**. {detail}"
    )
    return marker, body


def build_feedback(
    send: Callable[..., Any] | None = None,
) -> Callable[[Mapping[str, Any]], None]:
    """Report a terminal request back to the issue that asked for it."""
    if send is None:
        from app.routers.github_research_bridge import _send_feedback as send  # noqa: PLC0415

    def _feedback(record: Mapping[str, Any]) -> None:
        prepared = _status_comment(record)
        if prepared is None:
            return
        marker, body = prepared
        provenance = dict(record.get("provenance") or {})
        send(
            repository=str(provenance["source_repository"]),
            issue_number=int(provenance["source_issue_number"]),
            marker=marker,
            message=body,
        )

    return _feedback


def build_executor(
    *,
    runner: ResearchRunner,
    store: RequestStore | None = None,
    feedback: Callable[[Mapping[str, Any]], None] | None = None,
    env: Mapping[str, str] | None = None,
) -> ResearchExecutor:
    return ResearchExecutor(
        store=store if store is not None else build_request_store(env=env),
        runner=runner,
        feedback=feedback if feedback is not None else build_feedback(),
    )


def run_once(
    *,
    runner: ResearchRunner,
    store: RequestStore | None = None,
    feedback: Callable[[Mapping[str, Any]], None] | None = None,
    env: Mapping[str, str] | None = None,
) -> ExecutionReport:
    """Execute at most one request, refusing while the worker is disabled.

    The gate is checked here rather than by the caller so that enabling
    research execution is one deployment decision with one observable name,
    not a property of which entry point somebody happened to call.
    """
    if not worker_enabled(env):
        return ExecutionReport(
            claimed=False,
            notes=[f"worker disabled; set {WORKER_ENABLED_ENV}=true to enable"],
        )
    return build_executor(runner=runner, store=store, feedback=feedback, env=env).execute_once()
