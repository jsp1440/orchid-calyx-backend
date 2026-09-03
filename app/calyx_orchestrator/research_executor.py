"""Governed BUILD-051 research request executor (Gates 4–6 of CALYX-RECOVERY-001).

Drives the state machine:
    queued_waiting_for_executor → queued → running → completed | blocked

Key design constraints:
- No production Knowledge Graph mutation.
- No taxonomy activation or scientific publication authority.
- No fabricated evidence: unavailable → explicit BLOCKED state, not a fallback answer.
- Exactly-once / idempotent: same request_id always produces the same project and
  the same artifact; replays detect and skip duplicate creation.
- Fail-closed: any unrecoverable retrieval failure transitions to blocked with a
  machine-readable blocker code.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.calyx_conversation.external_literature import search_europe_pmc

SCHEMA_VERSION = "calyx-research-executor/v1"

_TERMINAL_STATES = frozenset({"completed", "blocked"})
_VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued_waiting_for_executor": frozenset({"queued", "blocked"}),
    "queued": frozenset({"running", "blocked"}),
    "running": frozenset({"completed", "blocked"}),
    "completed": frozenset(),
    "blocked": frozenset(),
}

# Governance boundaries — these never change without explicit owner authorization.
_AUTHORITY = {
    "knowledge_graph_mutation_authorized": False,
    "taxonomy_activation_authorized": False,
    "scientific_publication_authorized": False,
    "production_deployment_authorized": False,
    "evidence_promotion_authorized": False,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class ResearchRequestStore:
    """In-process store for BUILD-051 research requests.

    Used directly in tests; in production the store delegates to the shared
    ``MEMORY`` dict and DB path in ``owner_operations``.  This class makes the
    executor independently testable without a running database.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[str, dict[str, Any]] = {}

    def upsert(self, record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Insert or return existing record. Returns (record, created)."""
        request_id = str(record["id"])
        with self._lock:
            if request_id in self._requests:
                return self._requests[request_id], False
            self._requests[request_id] = dict(record)
            return self._requests[request_id], True

    def get(self, request_id: str) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._requests[request_id]) if request_id in self._requests else None

    def update_status(
        self,
        request_id: str,
        *,
        status: str,
        blocker: str | None = None,
        artifact_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            record = self._requests.get(request_id)
            if record is None:
                raise LookupError("RESEARCH_REQUEST_NOT_FOUND")
            current = record.get("status", "")
            allowed = _VALID_TRANSITIONS.get(current, frozenset())
            if status not in allowed:
                raise ValueError(
                    f"RESEARCH_REQUEST_INVALID_TRANSITION:{current}→{status}"
                )
            record["status"] = status
            record["updated_at"] = _utc_now()
            if blocker is not None:
                record["blocker"] = blocker
            elif status != "blocked":
                record.pop("blocker", None)
            if artifact_ids:
                record.setdefault("artifact_ids", [])
                for aid in artifact_ids:
                    if aid not in record["artifact_ids"]:
                        record["artifact_ids"].append(aid)
            return dict(record)

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._requests.values()]


class ResearchExecutorResult:
    """Structured result from one executor run."""

    def __init__(
        self,
        *,
        request_id: str,
        status: str,
        project_id: str | None = None,
        artifact_ids: list[str] | None = None,
        blocker: str | None = None,
        blocker_code: str | None = None,
        provenance: dict[str, Any] | None = None,
        external_literature: dict[str, Any] | None = None,
        review_required: bool = True,
    ) -> None:
        self.request_id = request_id
        self.status = status
        self.project_id = project_id
        self.artifact_ids = artifact_ids or []
        self.blocker = blocker
        self.blocker_code = blocker_code
        self.provenance = provenance or {}
        self.external_literature = external_literature or {}
        self.review_required = review_required
        self.authority = dict(_AUTHORITY)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "request_id": self.request_id,
            "status": self.status,
            "project_id": self.project_id,
            "artifact_ids": self.artifact_ids,
            "blocker": self.blocker,
            "blocker_code": self.blocker_code,
            "provenance": self.provenance,
            "external_literature_summary": {
                "result_count": len(
                    self.external_literature.get("results") or []
                ),
                "status": self.external_literature.get("status", "not_attempted"),
                "review_required": self.external_literature.get("review_required", True),
                "automatic_publication": False,
                "knowledge_graph_mutation": False,
            },
            "review_required": self.review_required,
            "authority": self.authority,
        }


class GovervedResearchExecutor:
    """Bounded executor for BUILD-051 research requests.

    Drives one request through the state machine, binds a ResearchStation
    project, acquires governed external literature for the identified taxa,
    and registers an immutable result artifact.

    This executor never:
    - promotes findings into the Knowledge Graph
    - activates or mutates taxonomy
    - publishes scientific conclusions
    - fabricates evidence when retrieval is unavailable
    """

    EXECUTOR_KEY = "calyx_research_executor_v1"
    OWNER_ID = "calyx-research-executor"

    def __init__(
        self,
        *,
        store: ResearchRequestStore | None = None,
        station: Any | None = None,
        artifact_registry: Any | None = None,
        workspace: Path | None = None,
    ) -> None:
        self._store = store or ResearchRequestStore()
        self._station = station
        self._artifact_registry = artifact_registry
        self._workspace = workspace
        # ImmutableArtifactRegistry stores only metadata; keep raw bytes here
        # so callers can read back the result content without a separate store.
        self._artifact_content: dict[str, bytes] = {}

    def get_result_content(self, artifact_id: str) -> bytes | None:
        """Return the raw bytes for a registered result artifact."""
        return self._artifact_content.get(artifact_id)

    def _get_station(self) -> Any:
        if self._station is not None:
            return self._station
        from app.calyx_orchestrator.artifact_registry import ImmutableArtifactRegistry
        from runtime.research_station import ResearchStationService
        return ResearchStationService(
            workspace=self._workspace,
            artifact_registry=self._artifact_registry or ImmutableArtifactRegistry(),
        )

    def _get_registry(self) -> Any:
        if self._artifact_registry is not None:
            return self._artifact_registry
        from app.calyx_orchestrator.artifact_registry import ImmutableArtifactRegistry
        return ImmutableArtifactRegistry()

    def execute(self, request: dict[str, Any]) -> ResearchExecutorResult:
        """Execute one BUILD-051 research request.

        Idempotent: if the request already reached a terminal state, returns
        its current state without re-running.

        Args:
            request: Full BUILD-051 request dict (from the research bridge or
                     ResearchRequestStore).

        Returns:
            ResearchExecutorResult with final status, artifact IDs, and provenance.
        """
        request_id = str(request.get("id") or "")
        if not request_id:
            raise ValueError("RESEARCH_REQUEST_ID_REQUIRED")

        # Idempotency: insert or retrieve existing record.
        record, _created = self._store.upsert(request)
        current_status = record.get("status", "queued_waiting_for_executor")

        if current_status in _TERMINAL_STATES:
            return ResearchExecutorResult(
                request_id=request_id,
                status=current_status,
                project_id=record.get("project_id"),
                artifact_ids=record.get("artifact_ids", []),
                blocker=record.get("blocker"),
                blocker_code=record.get("blocker_code"),
                provenance={"idempotent_replay": True, "created": False},
            )

        # Transition: queued_waiting_for_executor → queued
        if current_status == "queued_waiting_for_executor":
            record = self._store.update_status(request_id, status="queued")
            current_status = "queued"

        # Extract taxa for literature acquisition.
        taxa: list[str] = list(record.get("taxa") or [])
        title = str(record.get("title") or "Research request")
        research_question = str(record.get("research_question") or title)
        provenance = dict(record.get("provenance") or {})

        # Derive a stable project_id from the request_id.
        project_id = f"proj-{_sha(f'research-executor:{request_id}')[:20]}"

        station = self._get_station()
        registry = self._get_registry()

        # Transition: queued → running (also persist project_id for replay)
        record = self._store.update_status(request_id, status="running")
        # Store project_id so terminal-state replay can return it.
        with self._store._lock:
            self._store._requests[request_id]["project_id"] = project_id

        # --- Bind Research Station project (idempotent) ---
        try:
            station.create_project(
                self.OWNER_ID,
                {
                    "project_id": project_id,
                    "title": title,
                    "objective": research_question,
                    "state": "active",
                    "created_at": record.get("created_at") or _utc_now(),
                },
            )
            # Add the primary research question.
            station.add_question(
                self.OWNER_ID,
                project_id,
                {
                    "text": research_question,
                    "rationale": "Sourced from BUILD-051 research request intake",
                },
            )
        except Exception as exc:  # noqa: BLE001 - fail closed on station binding failures
            blocker = str(exc)
            self._store.update_status(
                request_id, status="blocked",
                blocker=blocker,
            )
            return ResearchExecutorResult(
                request_id=request_id,
                status="blocked",
                project_id=project_id,
                blocker=blocker,
                blocker_code="RESEARCH_STATION_BIND_FAILED",
                provenance=provenance,
            )

        # --- Acquire external literature (fail-closed) ---
        external_lit: dict[str, Any] = {
            "status": "not_attempted",
            "results": [],
            "review_required": True,
            "automatic_publication": False,
            "knowledge_graph_mutation": False,
        }
        lit_blocker: str | None = None

        try:
            external_lit = search_europe_pmc(
                research_question,
                limit=8,
                taxa=taxa if taxa else None,
            )
            if not external_lit.get("results"):
                external_lit["status"] = "EMPTY"
                lit_blocker = (
                    "External literature search returned no results for the "
                    f"given taxa {taxa!r}. Evidence acquisition incomplete."
                )
        except Exception as exc:  # noqa: BLE001 - fail closed on retrieval failures
            # Network or other failure — mark explicitly unavailable.
            external_lit = {
                "status": "UNAVAILABLE",
                "results": [],
                "result_count": 0,
                "error": str(exc),
                "review_required": True,
                "automatic_publication": False,
                "knowledge_graph_mutation": False,
            }
            lit_blocker = f"External literature unavailable: {exc}"

        # Produce a result artifact even when literature is unavailable
        # so the request has a durable, reviewable record.
        result_payload = {
            "schema_version": SCHEMA_VERSION,
            "request_id": request_id,
            "project_id": project_id,
            "title": title,
            "taxa": taxa,
            "research_question": research_question,
            "external_literature": {
                "provider": external_lit.get("provider", "Europe PMC"),
                "status": external_lit.get("status", "UNAVAILABLE"),
                "result_count": len(external_lit.get("results") or []),
                "query_plan": external_lit.get("query_plan", []),
                "results": (external_lit.get("results") or [])[:25],
                "review_required": True,
                "automatic_publication": False,
                "knowledge_graph_mutation": False,
            },
            "evidence_state": (
                "REVIEWED_EXTERNAL_DISCOVERY"
                if external_lit.get("results")
                else "UNAVAILABLE"
            ),
            "authority": dict(_AUTHORITY),
            "provenance": {
                **provenance,
                "executor_key": self.EXECUTOR_KEY,
                "executed_at": _utc_now(),
            },
            "review_required": True,
        }

        content = json.dumps(result_payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        artifact_id = f"research-result:{_sha(_stable(result_payload))[:32]}"

        try:
            from app.calyx_orchestrator.artifact_registry import (
                ArtifactRegistration,
            )
            registration = ArtifactRegistration(
                artifact_id=artifact_id,
                content=content,
                media_type="application/json",
                source_uri=f"calyx-research-executor:{request_id}",
                producer_assignment_id=f"executor:{self.EXECUTOR_KEY}:{request_id}",
                license=None,
                evidence_uris=tuple(
                    f"europe-pmc:{r.get('pmid') or r.get('doi') or r.get('title', '')}"
                    for r in (external_lit.get("results") or [])[:5]
                    if r.get("pmid") or r.get("doi")
                ),
                metadata={
                    "request_id": request_id,
                    "taxa": taxa,
                    "evidence_state": result_payload["evidence_state"],
                    "review_required": True,
                    "knowledge_graph_mutation_authorized": False,
                    "scientific_publication_authorized": False,
                },
            )
            registry.register(registration)
            self._artifact_content[artifact_id] = content

            # Attach the artifact to the research project.
            station.attach(
                self.OWNER_ID,
                project_id,
                {
                    "kind": "artifact_registry",
                    "source_id": artifact_id,
                    "note": "Research result artifact — requires human review before use",
                },
            )
        except Exception as exc:  # noqa: BLE001 - fail closed on artifact registration failures
            self._store.update_status(
                request_id, status="blocked",
                blocker=f"Artifact registration failed: {exc}",
            )
            return ResearchExecutorResult(
                request_id=request_id,
                status="blocked",
                project_id=project_id,
                blocker=str(exc),
                blocker_code="RESEARCH_ARTIFACT_REGISTRATION_FAILED",
                provenance=provenance,
                external_literature=external_lit,
            )

        # If literature was unavailable/empty, transition to blocked.
        if lit_blocker:
            self._store.update_status(
                request_id, status="blocked",
                blocker=lit_blocker,
                artifact_ids=[artifact_id],
            )
            return ResearchExecutorResult(
                request_id=request_id,
                status="blocked",
                project_id=project_id,
                artifact_ids=[artifact_id],
                blocker=lit_blocker,
                blocker_code="LITERATURE_UNAVAILABLE_OR_EMPTY",
                provenance=provenance,
                external_literature=external_lit,
            )

        # Transition: running → completed
        self._store.update_status(
            request_id, status="completed",
            artifact_ids=[artifact_id],
        )
        return ResearchExecutorResult(
            request_id=request_id,
            status="completed",
            project_id=project_id,
            artifact_ids=[artifact_id],
            provenance=provenance,
            external_literature=external_lit,
            review_required=True,
        )


def build_executor(
    *,
    workspace: Path | None = None,
    store: ResearchRequestStore | None = None,
) -> GovervedResearchExecutor:
    """Factory: create a governed research executor with canonical defaults."""
    from app.calyx_orchestrator.artifact_registry import ImmutableArtifactRegistry
    from runtime.research_station import ResearchStationService, research_root

    registry = ImmutableArtifactRegistry()
    station = ResearchStationService(
        workspace=workspace or research_root(),
        artifact_registry=registry,
    )
    return GovervedResearchExecutor(
        store=store or ResearchRequestStore(),
        station=station,
        artifact_registry=registry,
        workspace=workspace or research_root(),
    )
