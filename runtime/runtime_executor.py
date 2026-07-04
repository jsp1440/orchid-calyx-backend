"""BUILD-012D runtime executor.

The executor consumes the BUILD-012C planner queue and turns queue items into
execution records. This first executor is intentionally deterministic and
file-backed so it can run safely in Render without requiring database access.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .runtime_planner import RuntimePlanner


REPO_ROOT = Path(__file__).resolve().parents[1]
EXECUTION_DIR = REPO_ROOT / "runtime" / "executions"


EXECUTABLE_STATES = {"queued", "running", "completed", "failed", "cancelled"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ExecutionEvent:
    event_type: str
    execution_id: str
    module_id: str | None = None
    message: str | None = None
    timestamp: str = field(default_factory=utc_now)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionRecord:
    execution_id: str
    module_id: str
    module_name: str
    job_name: str
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: float | None = None
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    memory_objects: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)

    def add_event(self, event_type: str, message: str | None = None, **details: Any) -> None:
        self.events.append(
            asdict(
                ExecutionEvent(
                    event_type=event_type,
                    execution_id=self.execution_id,
                    module_id=self.module_id,
                    message=message,
                    details=details,
                )
            )
        )


class RuntimeWorker:
    """Minimal module worker for BUILD-012D.

    Later builds can replace this with module-specific workers. For now each
    worker validates the queue item and emits a deterministic result.
    """

    def __init__(self, queue_item: dict[str, Any]) -> None:
        self.queue_item = queue_item

    def execute(self) -> dict[str, Any]:
        return {
            "module_id": self.queue_item["module_id"],
            "module_name": self.queue_item["module_name"],
            "action": self.queue_item.get("action"),
            "status": "completed",
            "message": f"{self.queue_item['module_name']} execution placeholder completed.",
            "executed_at": utc_now(),
        }


class RuntimeExecutor:
    """Execute planner queue items and persist execution records."""

    def __init__(self, execution_dir: Path | None = None) -> None:
        self.execution_dir = execution_dir or EXECUTION_DIR
        self.execution_dir.mkdir(parents=True, exist_ok=True)

    def execute_queue(self, limit: int | None = None) -> dict[str, Any]:
        queue = RuntimePlanner().queue()["queue"]
        if limit is not None:
            queue = queue[:limit]

        records = [self.execute_item(item) for item in queue]
        return {
            "build": "BUILD-012D",
            "status": "completed",
            "executed_count": len(records),
            "executions": [asdict(record) for record in records],
        }

    def execute_module(self, module_id: str) -> dict[str, Any]:
        wanted = module_id.lower()
        for item in RuntimePlanner().queue()["queue"]:
            if item["module_id"].lower() == wanted or item["module_name"].lower() == wanted:
                record = self.execute_item(item)
                return {"build": "BUILD-012D", "status": "completed", "execution": asdict(record)}
        return {
            "build": "BUILD-012D",
            "status": "not_found_or_not_selectable",
            "module_id": module_id,
        }

    def execute_item(self, item: dict[str, Any]) -> ExecutionRecord:
        execution_id = self._new_execution_id()
        record = ExecutionRecord(
            execution_id=execution_id,
            module_id=item["module_id"],
            module_name=item["module_name"],
            job_name=item["job_name"],
            status="queued",
        )
        record.add_event("execution_queued", "Execution record created from planner queue.")
        started = datetime.now(timezone.utc)
        record.started_at = started.isoformat()
        record.status = "running"
        record.add_event("execution_started", "Worker started.")

        try:
            result = RuntimeWorker(item).execute()
            record.result = result
            record.status = "completed"
            record.add_event("execution_completed", result.get("message"))
        except Exception as exc:  # pragma: no cover - defensive safety net
            record.status = "failed"
            record.error = str(exc)
            record.add_event("execution_failed", str(exc))
        finally:
            finished = datetime.now(timezone.utc)
            record.finished_at = finished.isoformat()
            record.duration_ms = round((finished - started).total_seconds() * 1000, 3)
            self._write_record(record)

        return record

    def list_executions(self, limit: int = 50) -> dict[str, Any]:
        records = []
        for path in sorted(self.execution_dir.glob("EXE-*.json"), reverse=True)[:limit]:
            records.append(self._read_json(path))
        return {
            "build": "BUILD-012D",
            "count": len(records),
            "executions": records,
        }

    def get_execution(self, execution_id: str) -> dict[str, Any] | None:
        path = self.execution_dir / f"{execution_id}.json"
        if not path.exists():
            return None
        return self._read_json(path)

    def history(self) -> dict[str, Any]:
        records = self.list_executions(limit=500)["executions"]
        completed = [record for record in records if record.get("status") == "completed"]
        failed = [record for record in records if record.get("status") == "failed"]
        durations = [record.get("duration_ms") for record in records if record.get("duration_ms") is not None]
        return {
            "build": "BUILD-012D",
            "total_executions": len(records),
            "completed": len(completed),
            "failed": len(failed),
            "success_rate": round(len(completed) / len(records), 3) if records else None,
            "average_duration_ms": round(sum(durations) / len(durations), 3) if durations else None,
            "last_execution": records[0] if records else None,
        }

    def events(self, limit: int = 100) -> dict[str, Any]:
        all_events = []
        for record in self.list_executions(limit=500)["executions"]:
            all_events.extend(record.get("events", []))
        all_events.sort(key=lambda event: event.get("timestamp", ""), reverse=True)
        return {
            "build": "BUILD-012D",
            "count": min(len(all_events), limit),
            "events": all_events[:limit],
        }

    def cancel(self, execution_id: str) -> dict[str, Any]:
        record = self.get_execution(execution_id)
        if not record:
            return {"status": "not_found", "execution_id": execution_id}
        if record.get("status") in {"completed", "failed", "cancelled"}:
            return {"status": "not_cancellable", "execution": record}
        record["status"] = "cancelled"
        record.setdefault("events", []).append(
            asdict(ExecutionEvent("execution_cancelled", execution_id, record.get("module_id"), "Cancelled by API request."))
        )
        self._write_dict(record)
        return {"status": "cancelled", "execution": record}

    def retry(self, execution_id: str) -> dict[str, Any]:
        record = self.get_execution(execution_id)
        if not record:
            return {"status": "not_found", "execution_id": execution_id}
        return self.execute_module(record["module_id"])

    def _new_execution_id(self) -> str:
        return f"EXE-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"

    def _write_record(self, record: ExecutionRecord) -> None:
        self._write_dict(asdict(record))

    def _write_dict(self, record: dict[str, Any]) -> None:
        path = self.execution_dir / f"{record['execution_id']}.json"
        path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")

    def _read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))
