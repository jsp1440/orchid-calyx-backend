"""CALYX Gate 2 — canonical research executor.

State machine (exactly one path per request):
  queued_waiting_for_executor → queued → running → completed | blocked

Governance boundaries (enforced, never overridden):
- No scientific publication authority.
- No Knowledge Graph mutation.
- No taxonomy activation.
- No production deployment.
- No paid provider activation (preserves NO_API_MODE).
- No sensitive-locality disclosure.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.calyx_orchestrator.artifact_registry import (
    ArtifactRegistration,
    ImmutableArtifactRegistry,
)
from runtime.research_station import ResearchStationService

# ── State machine constants ─────────────────────────────────────────────

TRANSITION_MAP: dict[str, frozenset[str]] = {
    "queued_waiting_for_executor": frozenset({"queued"}),
    "queued": frozenset({"running"}),
    "running": frozenset({"completed", "blocked"}),
}
TERMINAL_STATES = frozenset({"completed", "blocked"})

# Bounded blocker codes — only codes from this set may be recorded.
VALID_BLOCKER_CODES = frozenset(
    {
        "NO_EXECUTOR_AVAILABLE",
        "PROVIDER_UNAVAILABLE",
        "RESEARCH_STATION_ERROR",
        "ARTIFACT_REGISTRATION_FAILED",
        "TIMEOUT",
        "GOVERNANCE_REFUSED",
        "EXTERNAL_DEPENDENCY_UNAVAILABLE",
        "UNKNOWN_ERROR",
    }
)


# ── Utility helpers ────────────────────────────────────────────────


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _project_id_for(request_id: str) -> str:
    return f"calyx-project-{_sha(request_id)[:20]}"


# ── In-memory fallback store (when DATABASE_URL is absent) ────────────────

_MEMORY_RESEARCH_PROJECTS: list[dict[str, Any]] = []


# ── Database helpers ───────────────────────────────────────────────


def _db_url() -> str | None:
    return os.environ.get("DATABASE_URL")


# ── Core executor ─────────────────────────────────────────────────


@dataclass
class ExecutionResult:
    request_id: str
    final_state: str
    project_id: str | None
    artifact_ids: list[str]
    blocker_code: str | None
    status_history: list[dict[str, Any]]


class CalyxResearchExecutorService:
    """Gate 2 — drives one durable research request through the full state machine.

    Supports both DB-backed (DATABASE_URL present) and in-memory (NO_API_MODE)
    operation.  The DB is authoritative when available; in-memory is the fallback
    for isolated tests and local development without a database.
    """

    def __init__(
        self,
        *,
        memory_requests: list[dict[str, Any]] | None = None,
        memory_projects: list[dict[str, Any]] | None = None,
        artifact_registry: ImmutableArtifactRegistry | None = None,
        github_feedback_fn: Callable[..., dict[str, Any]] | None = None,
        station_workspace: Path | None = None,
    ) -> None:
        # When memory_requests is explicitly provided (even as empty list), use
        # in-memory mode for this instance.  Only use DB when it is None *and*
        # DATABASE_URL is available.
        self._explicit_memory = memory_requests is not None
        self._mem_requests: list[dict[str, Any]] = (
            memory_requests if memory_requests is not None else []
        )
        self._mem_projects: list[dict[str, Any]] = (
            memory_projects if memory_projects is not None else _MEMORY_RESEARCH_PROJECTS
        )
        self._registry = artifact_registry or ImmutableArtifactRegistry()
        self._feedback_fn = github_feedback_fn
        #: Set when a durable database write or a station write could not be
        #: completed. The in-memory/cache copy still exists, but it is no longer
        #: authoritative and a caller must be able to see that instead of
        #: assuming durability. Never silently cleared.
        self.durability_degraded: str | None = None
        self._station = ResearchStationService(
            workspace=station_workspace or Path(
                os.getenv("CALYX_RESEARCH_STATION_DIR", "/tmp/calyx/research-station")
            )
        )

    def _mark_degraded(self, exc: BaseException) -> None:
        """Record a failed durable write instead of swallowing it.

        Runtime DDL was removed from this module (the tables are created by
        migrations/CALYX-RECOVERY-001-research-executor-tables.sql), so a
        missing table now surfaces here rather than being masked.
        """
        self.durability_degraded = f"{type(exc).__name__}: {exc}"

    # ── Public API ──────────────────────────────────────────────────

    def claim(self, request_id: str) -> dict[str, Any]:
        """Idempotent claim: queued_waiting_for_executor → queued.

        Returns the current request record.  If the request is already queued
        or beyond, this is a no-op and returns the existing state (idempotent).
        """
        request = self._load_request(request_id)
        if request is None:
            raise LookupError(f"RESEARCH_REQUEST_NOT_FOUND:{request_id}")
        current = request.get("status", "")
        if current in TERMINAL_STATES or current in {"queued", "running"}:
            return request  # already claimed — idempotent
        if current != "queued_waiting_for_executor":
            raise ValueError(f"RESEARCH_REQUEST_STATE_INVALID:{current}")
        return self._transition(request, "queued", actor="calyx_executor", detail={})

    def start_running(self, request_id: str) -> dict[str, Any]:
        """queued → running.  Binds and persists the Research Station project.

        This is the point where the project/question/provenance is committed to
        the canonical database.  The Research Station filesystem record is
        secondary; the DB record is authoritative.
        """
        request = self._load_request(request_id)
        if request is None:
            raise LookupError(f"RESEARCH_REQUEST_NOT_FOUND:{request_id}")
        current = request.get("status", "")
        if current == "running":
            return request  # already running — idempotent
        if current != "queued":
            raise ValueError(f"RESEARCH_REQUEST_STATE_INVALID:{current}")

        project_id = _project_id_for(request_id)
        self._bind_project(request, project_id)
        updated = self._transition(
            request,
            "running",
            actor="calyx_executor",
            detail={"research_project_id": project_id},
        )
        updated["research_project_id"] = project_id
        self._patch_request_field(request_id, "research_project_id", project_id)
        return updated

    def complete(
        self,
        request_id: str,
        *,
        artifact_ids: list[str],
        notes: str = "",
    ) -> dict[str, Any]:
        """running → completed.  Writes artifact IDs back to the original request."""
        request = self._load_request(request_id)
        if request is None:
            raise LookupError(f"RESEARCH_REQUEST_NOT_FOUND:{request_id}")
        current = request.get("status", "")
        if current == "completed":
            return request  # idempotent
        if current != "running":
            raise ValueError(f"RESEARCH_REQUEST_STATE_INVALID:{current}")
        detail: dict[str, Any] = {"artifact_ids": artifact_ids, "notes": notes}
        updated = self._transition(
            request, "completed", actor="calyx_executor", detail=detail
        )
        updated["result_artifact_ids"] = artifact_ids
        updated["blocker"] = None
        self._patch_request_field(request_id, "result_artifact_ids", artifact_ids)
        self._patch_request_field(request_id, "blocker", None)
        return updated

    def block(
        self,
        request_id: str,
        *,
        code: str,
        detail: str = "",
    ) -> dict[str, Any]:
        """running → blocked.  Records a bounded, machine-readable blocker code."""
        if code not in VALID_BLOCKER_CODES:
            raise ValueError(f"INVALID_BLOCKER_CODE:{code}")
        request = self._load_request(request_id)
        if request is None:
            raise LookupError(f"RESEARCH_REQUEST_NOT_FOUND:{request_id}")
        current = request.get("status", "")
        if current == "blocked":
            return request  # idempotent
        if current != "running":
            raise ValueError(f"RESEARCH_REQUEST_STATE_INVALID:{current}")
        blocker_payload = {"code": code, "detail": detail, "at": _utc_now()}
        transition_detail: dict[str, Any] = {"blocker": blocker_payload}
        updated = self._transition(
            request, "blocked", actor="calyx_executor", detail=transition_detail
        )
        updated["blocker"] = blocker_payload
        updated["result_artifact_ids"] = []
        self._patch_request_field(request_id, "blocker", blocker_payload)
        self._patch_request_field(request_id, "result_artifact_ids", [])
        return updated

    def execute_fake(self, request_id: str) -> ExecutionResult:
        """Deterministic fake execution proving the complete state machine.

        This is the Gate 2 acceptance executor.  It:
        1. Claims the request (queued_waiting_for_executor → queued).
        2. Transitions to running, binds the Research Station project.
        3. Registers an immutable fake result artifact.
        4. Transitions to completed, writes artifact IDs back.
        5. Sends idempotent GitHub feedback if configured.
        6. Does NOT mutate the Knowledge Graph, publish science, or activate
           taxonomy.

        Idempotent: if the request is already completed, returns the recorded
        result without re-running any steps.
        """
        existing = self._load_request(request_id)
        if existing is not None and existing.get("status") in TERMINAL_STATES:
            # Already reached a terminal state — return recorded result (idempotent).
            artifact_ids = existing.get("result_artifact_ids") or []
            blocker = existing.get("blocker")
            blocker_code: str | None = None
            if isinstance(blocker, dict):
                blocker_code = str(blocker.get("code") or "")
            elif isinstance(blocker, str):
                blocker_code = blocker
            return ExecutionResult(
                request_id=request_id,
                final_state=existing["status"],
                project_id=existing.get("research_project_id"),
                artifact_ids=list(artifact_ids),
                blocker_code=blocker_code,
                status_history=existing.get("status_history", []),
            )

        self.claim(request_id)
        step2 = self.start_running(request_id)
        project_id: str = step2.get("research_project_id", _project_id_for(request_id))

        # Register a fake result artifact through the immutable evidence boundary.
        result_payload = json.dumps(
            {
                "schema": "calyx-fake-executor-result/v1",
                "request_id": request_id,
                "project_id": project_id,
                "note": "Fake executor result — Gate 2 state machine proof.",
                "authority": {
                    "scientific_publication": False,
                    "knowledge_graph_mutation": False,
                    "taxonomy_activation": False,
                    "production_deployment": False,
                },
            },
            sort_keys=True,
        ).encode("utf-8")
        artifact_id = f"calyx-result-{_sha(request_id)[:20]}"
        registration = ArtifactRegistration(
            artifact_id=artifact_id,
            content=result_payload,
            media_type="application/json",
            source_uri=f"calyx://research-executor/fake/{request_id}",
            producer_assignment_id=request_id,
            evidence_uris=(f"calyx://research-request/{request_id}",),
        )
        reg_result = self._registry.register(registration)

        step3 = self.complete(
            request_id,
            artifact_ids=[reg_result.record.artifact_id],
            notes="Fake executor — Gate 2 proof run.",
        )
        history: list[dict[str, Any]] = step3.get("status_history", [])

        # Idempotent GitHub feedback if configured.
        self._send_github_feedback(step3)

        return ExecutionResult(
            request_id=request_id,
            final_state=step3["status"],
            project_id=project_id,
            artifact_ids=[reg_result.record.artifact_id],
            blocker_code=None,
            status_history=history,
        )

    # ── Internal state machine ───────────────────────────────────────────

    def _load_request(self, request_id: str) -> dict[str, Any] | None:
        if self._explicit_memory:
            return self._mem_load_request(request_id)
        url = _db_url()
        if url:
            return self._db_load_request(request_id)
        return self._mem_load_request(request_id)

    def _mem_load_request(self, request_id: str) -> dict[str, Any] | None:
        for item in self._mem_requests:
            payload = item.get("payload")
            record = payload if isinstance(payload, dict) else item
            if record.get("id") == request_id:
                return dict(record)
        return None

    def _db_load_request(self, request_id: str) -> dict[str, Any] | None:
        try:
            import psycopg
            from psycopg.rows import dict_row

            url = _db_url()
            if not url:
                return None
            with psycopg.connect(url, row_factory=dict_row, connect_timeout=5) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT payload FROM oc_admin.build051_research_requests WHERE id = %s",
                    (request_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return dict(row["payload"])
        except Exception:  # noqa: BLE001
            return None

    def _transition(
        self,
        request: dict[str, Any],
        new_state: str,
        *,
        actor: str,
        detail: dict[str, Any],
    ) -> dict[str, Any]:
        old_state = request.get("status", "unknown")
        allowed = TRANSITION_MAP.get(old_state, frozenset())
        if new_state not in allowed:
            raise ValueError(
                f"ILLEGAL_TRANSITION:{old_state}->{new_state}"
            )
        now = _utc_now()
        transition = {
            "from_state": old_state,
            "to_state": new_state,
            "actor": actor,
            "at": now,
            "detail": detail,
        }
        history: list[dict[str, Any]] = list(request.get("status_history", []))
        history.append(transition)
        updated = {
            **request,
            "status": new_state,
            "updated_at": now,
            "status_history": history,
        }
        request_id = request["id"]
        self._persist_request(request_id, updated)
        self._persist_history_entry(request_id, transition)
        return updated

    def _persist_request(self, request_id: str, payload: dict[str, Any]) -> None:
        if self._explicit_memory:
            self._mem_persist_request(request_id, payload)
            return
        url = _db_url()
        if url:
            self._db_persist_request(request_id, payload)
        else:
            self._mem_persist_request(request_id, payload)

    def _mem_persist_request(self, request_id: str, payload: dict[str, Any]) -> None:
        for i, item in enumerate(self._mem_requests):
            record = item.get("payload") if isinstance(item.get("payload"), dict) else item
            if record.get("id") == request_id:
                if isinstance(item.get("payload"), dict):
                    self._mem_requests[i] = {**item, "payload": payload}
                else:
                    self._mem_requests[i] = payload
                return
        self._mem_requests.insert(0, payload)

    def _db_persist_request(self, request_id: str, payload: dict[str, Any]) -> None:
        try:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg.types.json import Jsonb

            url = _db_url()
            if not url:
                return
            with psycopg.connect(url, row_factory=dict_row, connect_timeout=5) as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE oc_admin.build051_research_requests
                    SET payload = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (Jsonb(payload), request_id),
                )
                conn.commit()
        except Exception as exc:  # noqa: BLE001
            self._mark_degraded(exc)

    def _patch_request_field(
        self, request_id: str, field: str, value: Any
    ) -> None:
        """Patch one field in the canonical request record without a full reload."""
        if self._explicit_memory:
            for item in self._mem_requests:
                record = item.get("payload") if isinstance(item.get("payload"), dict) else item
                if record.get("id") == request_id:
                    if isinstance(item.get("payload"), dict):
                        item["payload"][field] = value
                    else:
                        item[field] = value
                    return
            return
        url = _db_url()
        if not url:
            # For in-memory: update the record in place
            for item in self._mem_requests:
                record = item.get("payload") if isinstance(item.get("payload"), dict) else item
                if record.get("id") == request_id:
                    if isinstance(item.get("payload"), dict):
                        item["payload"][field] = value
                    else:
                        item[field] = value
                    return
            return
        try:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg.types.json import Jsonb

            with psycopg.connect(url, row_factory=dict_row, connect_timeout=5) as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE oc_admin.build051_research_requests
                    SET payload = jsonb_set(payload, %s, %s, true),
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        "{" + field + "}",
                        Jsonb(value),
                        request_id,
                    ),
                )
                conn.commit()
        except Exception as exc:  # noqa: BLE001
            self._mark_degraded(exc)

    def _persist_history_entry(
        self, request_id: str, transition: dict[str, Any]
    ) -> None:
        if self._explicit_memory:
            return  # history is embedded in the request payload; no separate table
        url = _db_url()
        if not url:
            return
        try:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg.types.json import Jsonb

            with psycopg.connect(url, row_factory=dict_row, connect_timeout=5) as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO oc_admin.calyx_research_state_history
                        (request_id, from_state, to_state, actor, detail)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        request_id,
                        transition["from_state"],
                        transition["to_state"],
                        transition["actor"],
                        Jsonb(transition.get("detail", {})),
                    ),
                )
                conn.commit()
        except Exception as exc:  # noqa: BLE001
            self._mark_degraded(exc)

    # ── Research Station project binding ─────────────────────────────

    def _bind_project(self, request: dict[str, Any], project_id: str) -> None:
        """Bind and persist the Research Station project to the canonical DB.

        The DB record is the authoritative durable store.  The filesystem
        (research_station) record is secondary — it is created if possible but
        its absence does not prevent progression.
        """
        request_id = request["id"]
        title = str(request.get("title") or request_id)[:200]
        question = str(
            request.get("research_question")
            or request.get("title")
            or request_id
        )[:1000]
        now = _utc_now()
        project_payload = {
            "schema": "calyx-research-project/v1",
            "project_id": project_id,
            "request_id": request_id,
            "title": title,
            "question": question,
            "provenance": request.get("provenance", {}),
            "taxa": request.get("taxa", []),
            "priority": request.get("priority", "medium"),
            "state": "active",
            "created_at": now,
            "updated_at": now,
            "private_by_default": True,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
            "taxonomy_activation_authorized": False,
            "production_deployment_authorized": False,
        }

        # 1. Canonical DB persistence (authoritative).
        self._persist_project(project_id, request_id, project_payload)

        # 2. Research Station filesystem (secondary, best-effort).
        try:
            owner_id = str(request.get("owner") or "calyx_executor")
            self._station.create_project(
                owner_id,
                {
                    "project_id": project_id,
                    "title": title,
                    "objective": question[:500],
                    "state": "active",
                    "created_at": now,
                },
            )
            self._station.add_question(
                owner_id,
                project_id,
                {
                    "text": question,
                    "rationale": f"Calyx Gate 2 research request {request_id}",
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._mark_degraded(exc)

    def _persist_project(
        self, project_id: str, request_id: str, payload: dict[str, Any]
    ) -> None:
        if self._explicit_memory:
            self._mem_persist_project(project_id, payload)
            return
        url = _db_url()
        if url:
            self._db_persist_project(project_id, request_id, payload)
        else:
            self._mem_persist_project(project_id, payload)

    def _mem_persist_project(
        self, project_id: str, payload: dict[str, Any]
    ) -> None:
        for item in self._mem_projects:
            if item.get("id") == project_id:
                return  # already exists — idempotent
        self._mem_projects.insert(0, {"id": project_id, "payload": payload})

    def _db_persist_project(
        self, project_id: str, request_id: str, payload: dict[str, Any]
    ) -> None:
        try:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg.types.json import Jsonb

            url = _db_url()
            if not url:
                return
            with psycopg.connect(url, row_factory=dict_row, connect_timeout=5) as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO oc_admin.calyx_research_projects
                        (id, request_id, payload, created_at, updated_at)
                    VALUES (%s, %s, %s, NOW(), NOW())
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (project_id, request_id, Jsonb(payload)),
                )
                conn.commit()
        except Exception as exc:  # noqa: BLE001
            self._mark_degraded(exc)

    # ── GitHub feedback ───────────────────────────────────────────────

    def _send_github_feedback(self, request: dict[str, Any]) -> None:
        if self._feedback_fn is None:
            return
        provenance = request.get("provenance") or {}
        repo = str(provenance.get("source_repository") or "")
        issue_number_raw = provenance.get("source_issue_number")
        request_id = request.get("id", "unknown")
        status = request.get("status", "unknown")
        if not repo or not issue_number_raw:
            return
        try:
            issue_number = int(issue_number_raw)
        except (TypeError, ValueError):
            return
        marker = f"<!-- calyx-research-bridge:{request_id} -->"
        artifact_ids = request.get("result_artifact_ids", [])
        blocker = request.get("blocker")
        if status == "completed":
            summary = (
                f"Research request **{request_id}** completed. "
                f"Result artifact IDs: {', '.join(artifact_ids) or 'none'}."
            )
        elif status == "blocked":
            code = blocker.get("code") if isinstance(blocker, dict) else str(blocker)
            summary = (
                f"Research request **{request_id}** blocked. "
                f"Blocker code: `{code}`."
            )
        else:
            summary = f"Research request **{request_id}** state: `{status}`."
        message = f"{marker}\n{summary}"
        try:
            self._feedback_fn(
                repository=repo,
                issue_number=issue_number,
                marker=marker,
                message=message,
            )
        except Exception:  # noqa: BLE001, S110
            pass
