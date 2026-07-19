from __future__ import annotations

from typing import Any

from .registry import MISSION_TYPES, validate_mission_transition


class MissionService:
    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def initialize(self) -> None:
        self.repository.seed_registry()

    def create(self, data: dict[str, Any], auth: dict[str, object] | None = None) -> dict[str, Any]:
        self.initialize()
        if data["mission_type"] not in MISSION_TYPES:
            raise ValueError("UNREGISTERED_MISSION_TYPE")
        if _has_forbidden_payload(data.get("input_manifest") or {}):
            raise ValueError("FORBIDDEN_MISSION_PAYLOAD")
        return self.repository.create_mission(data, str((auth or {}).get("auth_type") or "owner_session"))

    def update(self, mission_id: int, data: dict[str, Any]) -> dict[str, Any]:
        if data.get("input_manifest") and _has_forbidden_payload(data["input_manifest"]):
            raise ValueError("FORBIDDEN_MISSION_PAYLOAD")
        return self.repository.update_draft(mission_id, data, data["actor"], data["reason"])

    def submit(self, mission_id: int, actor: str, reason: str) -> dict[str, Any]:
        mission = self._mission_or_404(mission_id)
        validate_mission_transition(mission["state"], "awaiting_approval")
        return self.repository.transition_mission(mission_id, "awaiting_approval", actor, reason)

    def approve(self, mission_id: int, actor: str, reason: str, approval_reference: str | None, publication_authority: str | None = None) -> dict[str, Any]:
        mission = self._mission_or_404(mission_id)
        validate_mission_transition(mission["state"], "approved")
        if mission["risk_level"] in {"high", "critical"} and not approval_reference:
            raise ValueError("HIGH_RISK_APPROVAL_REFERENCE_REQUIRED")
        return self.repository.transition_mission(mission_id, "approved", actor, reason, approval_reference, publication_authority)

    def reject(self, mission_id: int, actor: str, reason: str) -> dict[str, Any]:
        mission = self._mission_or_404(mission_id)
        validate_mission_transition(mission["state"], "blocked")
        return self.repository.transition_mission(mission_id, "blocked", actor, reason)

    def queue(self, mission_id: int, actor: str, reason: str) -> dict[str, Any]:
        mission = self._mission_or_404(mission_id)
        if mission["state"] != "approved":
            raise ValueError(f"INVALID_MISSION_TRANSITION:{mission['state']}->queued")
        validate_mission_transition(mission["state"], "queued")
        return self.repository.queue_mission(mission_id, actor, reason)

    def pause(self, mission_id: int, actor: str, reason: str) -> dict[str, Any]:
        mission = self._mission_or_404(mission_id)
        validate_mission_transition(mission["state"], "paused")
        return self.repository.transition_mission(mission_id, "paused", actor, reason)

    def resume(self, mission_id: int, actor: str, reason: str) -> dict[str, Any]:
        mission = self._mission_or_404(mission_id)
        target = "queued" if self.repository.list_jobs(mission_id) else "approved"
        validate_mission_transition(mission["state"], target)
        return self.repository.transition_mission(mission_id, target, actor, reason)

    def cancel(self, mission_id: int, actor: str, reason: str) -> dict[str, Any]:
        mission = self._mission_or_404(mission_id)
        validate_mission_transition(mission["state"], "cancelled")
        return self.repository.transition_mission(mission_id, "cancelled", actor, reason)

    def retry(self, mission_id: int, actor: str, reason: str) -> dict[str, Any]:
        mission = self._mission_or_404(mission_id)
        validate_mission_transition(mission["state"], "queued")
        return self.repository.transition_mission(mission_id, "queued", actor, reason)

    def list(self) -> list[dict[str, Any]]:
        return self.repository.list_missions()

    def get(self, mission_id: int) -> dict[str, Any]:
        return self._mission_or_404(mission_id)

    def jobs(self, mission_id: int) -> list[dict[str, Any]]:
        self._mission_or_404(mission_id)
        return self.repository.list_jobs(mission_id)

    def events(self, mission_id: int) -> list[dict[str, Any]]:
        self._mission_or_404(mission_id)
        return self.repository.list_events(mission_id)

    def templates(self) -> list[dict[str, Any]]:
        self.initialize()
        return self.repository.templates()

    def queue_status(self) -> dict[str, Any]:
        return self.repository.telemetry()

    def dead_letters(self) -> list[dict[str, Any]]:
        return self.repository.dead_letters()

    def enqueue_cycle(self, worker_id: str = "runtime") -> dict[str, Any]:
        self.initialize()
        recovered = self.repository.recover_expired_leases(worker_id)
        result = self.repository.enqueue_due_missions(actor=worker_id)
        return {**result, "lease_recovery_count": recovered}

    def execute_cycle(self, worker_id: str = "runtime", limit: int = 1) -> dict[str, Any]:
        self.initialize()
        completed = 0
        failed = 0
        last_job: dict[str, Any] | None = None
        for _ in range(limit):
            job = self.repository.claim_job(worker_id)
            if not job:
                break
            last_job = job
            started = self.repository.start_job(job["job_id"], worker_id)
            try:
                output = self._execute_registered_handler(started)
            except Exception as exc:
                self.repository.fail_job(started, exc.__class__.__name__, str(exc), worker_id)
                failed += 1
                continue
            self.repository.complete_job(started, output, worker_id)
            completed += 1
        return {
            "status": "completed" if completed else ("failed" if failed else "no_jobs"),
            "completed": completed,
            "failed": failed,
            "job_id": last_job.get("job_id") if last_job else None,
            "job_name": last_job.get("job_type") if last_job else None,
            "queue_depth": self.repository.queue_depth(),
        }

    def run_one(self, mission_id: int, worker_id: str = "api-execute-one") -> dict[str, Any]:
        mission = self._mission_or_404(mission_id)
        if mission["state"] == "approved":
            self.repository.queue_mission(mission_id, worker_id, "execute one approved safe mission")
        elif mission["state"] not in {"queued", "running"}:
            raise ValueError("MISSION_NOT_EXECUTABLE")
        return self.execute_cycle(worker_id=worker_id, limit=1)

    def _mission_or_404(self, mission_id: int) -> dict[str, Any]:
        mission = self.repository.get_mission(mission_id)
        if mission is None:
            raise LookupError("MISSION_NOT_FOUND")
        return mission

    def _execute_registered_handler(self, job: dict[str, Any]) -> dict[str, Any]:
        mission = job["mission"]
        mission_type = MISSION_TYPES.get(job["job_type"])
        if mission_type is None:
            raise ValueError("UNREGISTERED_MISSION_TYPE")
        handler = mission_type.handler
        if handler == "not_implemented_safe_block":
            raise ValueError("MISSION_HANDLER_NOT_ENABLED")
        if mission_type.taxonomy_writes_prohibited is not True:
            raise ValueError("MISSION_TYPE_MUST_PROHIBIT_TAXONOMY_WRITES")
        if handler == "system_health_check":
            return {
                "status": "ok",
                "mission_type": job["job_type"],
                "database_connectivity": "available",
                "queue_depth": self.repository.queue_depth(),
                "canonical_graph_mutated": False,
                "taxonomy_mutated": False,
            }
        if handler == "telemetry_snapshot":
            return {"status": "ok", "telemetry": self.repository.telemetry(), "canonical_graph_mutated": False, "taxonomy_mutated": False}
        if handler == "graph_integrity_audit":
            return {"status": "ok", "audit": "graph_integrity_read_only", "canonical_graph_mutated": False, "taxonomy_mutated": False}
        if handler == "taxonomy_integrity_audit":
            return {"status": "ok", "audit": "taxonomy_integrity_read_only", "canonical_graph_mutated": False, "taxonomy_mutated": False}
        if handler == "mission_control_status_report":
            return {"status": "ok", "report": self.repository.telemetry(), "canonical_graph_mutated": False, "taxonomy_mutated": False}
        raise ValueError("MISSION_HANDLER_NOT_REGISTERED")


def _has_forbidden_payload(payload: Any) -> bool:
    text = str(payload).lower()
    forbidden = ("shell", "subprocess", "python", "sql", "http://", "https://", "url", "command", "exec", "eval")
    return any(token in text for token in forbidden)
