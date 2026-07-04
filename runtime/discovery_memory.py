"""BUILD-015 discovery memory.

This module persists BUILD-014 autonomous discovery snapshots so Calyx can compare
current and previous runtime state, detect changes, and preserve discovery
history across requests.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .autonomous_discovery import AutonomousDiscoveryEngine


REPO_ROOT = Path(__file__).resolve().parents[1]
MEMORY_DIR = REPO_ROOT / "runtime" / "discovery_memory"
LATEST_PATH = MEMORY_DIR / "latest.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class DiscoverySnapshotSummary:
    snapshot_id: str
    captured_at: str
    modules: int
    capabilities: int
    graph_nodes: int
    graph_edges: int
    recommendations: int
    brain_connected: bool | None = None


@dataclass
class DiscoveryDiff:
    build: str = "BUILD-015"
    status: str = "compared"
    previous_snapshot_id: str | None = None
    current_snapshot_id: str | None = None
    added_modules: list[str] = field(default_factory=list)
    removed_modules: list[str] = field(default_factory=list)
    added_capabilities: list[str] = field(default_factory=list)
    removed_capabilities: list[str] = field(default_factory=list)
    graph_edge_delta: int = 0
    recommendation_delta: int = 0


class DiscoveryMemoryStore:
    """File-backed discovery memory store."""

    def __init__(self, memory_dir: Path | None = None, engine: AutonomousDiscoveryEngine | None = None) -> None:
        self.memory_dir = memory_dir or MEMORY_DIR
        self.latest_path = self.memory_dir / "latest.json"
        self.engine = engine or AutonomousDiscoveryEngine()
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def capture(self) -> dict[str, Any]:
        payload = self.engine.discover(write_cache=True)
        snapshot_id = (
            f"DSM-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}-{uuid.uuid4().hex[:8]}"
        )
        record = {
            "build": "BUILD-015",
            "snapshot_id": snapshot_id,
            "captured_at": utc_now(),
            "source_build": payload.get("build"),
            "summary": payload.get("summary", {}),
            "modules": payload.get("modules", []),
            "capabilities": payload.get("capabilities", []),
            "graph": payload.get("graph", {}),
            "recommendations": payload.get("recommendations", []),
        }
        path = self.memory_dir / f"{snapshot_id}.json"
        path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        self.latest_path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        return record

    def list_snapshots(self, limit: int = 20) -> dict[str, Any]:
        records = [self._summary_from_record(self._read_json(path)) for path in self._snapshot_paths()]
        records.sort(key=lambda item: item.captured_at, reverse=True)
        return {
            "build": "BUILD-015",
            "count": min(len(records), limit),
            "snapshots": [asdict(item) for item in records[:limit]],
        }

    def latest(self) -> dict[str, Any]:
        if self.latest_path.exists():
            return self._read_json(self.latest_path)
        return self.capture()

    def diff_latest(self) -> dict[str, Any]:
        paths = self._snapshot_paths()
        if len(paths) < 2:
            current = self.latest() if paths else self.capture()
            diff = DiscoveryDiff(current_snapshot_id=current.get("snapshot_id"), status="insufficient_history")
            return asdict(diff)
        records = [self._read_json(path) for path in paths]
        records.sort(key=lambda item: item.get("captured_at", ""), reverse=True)
        return asdict(self._diff(records[1], records[0]))

    def health(self) -> dict[str, Any]:
        latest = self.latest()
        summary = latest.get("summary", {})
        snapshots = self.list_snapshots(limit=100)
        return {
            "build": "BUILD-015",
            "status": "healthy",
            "snapshot_count": snapshots.get("count"),
            "latest_snapshot_id": latest.get("snapshot_id"),
            "latest_captured_at": latest.get("captured_at"),
            "latest_summary": summary,
            "recommendations": self._memory_recommendations(latest),
        }

    def timeline(self, limit: int = 20) -> dict[str, Any]:
        snapshots = self.list_snapshots(limit=limit)["snapshots"]
        return {
            "build": "BUILD-015",
            "count": len(snapshots),
            "timeline": [
                {
                    "snapshot_id": item["snapshot_id"],
                    "captured_at": item["captured_at"],
                    "modules": item["modules"],
                    "capabilities": item["capabilities"],
                    "graph_edges": item["graph_edges"],
                    "recommendations": item["recommendations"],
                }
                for item in snapshots
            ],
        }

    def _snapshot_paths(self) -> list[Path]:
        return sorted(path for path in self.memory_dir.glob("DSM-*.json") if path.is_file())

    def _read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _summary_from_record(self, record: dict[str, Any]) -> DiscoverySnapshotSummary:
        summary = record.get("summary", {})
        return DiscoverySnapshotSummary(
            snapshot_id=record.get("snapshot_id"),
            captured_at=record.get("captured_at"),
            modules=summary.get("modules", 0),
            capabilities=summary.get("capabilities", 0),
            graph_nodes=summary.get("graph_nodes", 0),
            graph_edges=summary.get("graph_edges", 0),
            recommendations=summary.get("recommendations", 0),
            brain_connected=summary.get("brain_connected"),
        )

    def _diff(self, previous: dict[str, Any], current: dict[str, Any]) -> DiscoveryDiff:
        previous_modules = {item.get("name") for item in previous.get("modules", []) if item.get("name")}
        current_modules = {item.get("name") for item in current.get("modules", []) if item.get("name")}
        previous_capabilities = {f"{item.get('provider')}::{item.get('name')}" for item in previous.get("capabilities", [])}
        current_capabilities = {f"{item.get('provider')}::{item.get('name')}" for item in current.get("capabilities", [])}
        return DiscoveryDiff(
            previous_snapshot_id=previous.get("snapshot_id"),
            current_snapshot_id=current.get("snapshot_id"),
            added_modules=sorted(current_modules - previous_modules),
            removed_modules=sorted(previous_modules - current_modules),
            added_capabilities=sorted(current_capabilities - previous_capabilities),
            removed_capabilities=sorted(previous_capabilities - current_capabilities),
            graph_edge_delta=current.get("summary", {}).get("graph_edges", 0) - previous.get("summary", {}).get("graph_edges", 0),
            recommendation_delta=current.get("summary", {}).get("recommendations", 0) - previous.get("summary", {}).get("recommendations", 0),
        )

    def _memory_recommendations(self, latest: dict[str, Any]) -> list[dict[str, Any]]:
        recs = []
        summary = latest.get("summary", {})
        if summary.get("recommendations", 0) > 0:
            recs.append({"priority": "HIGH", "recommendation": "Review current discovery recommendations", "reason": f"{summary.get('recommendations')} active recommendation(s) exist."})
        recs.append({"priority": "MEDIUM", "recommendation": "Persist discovery snapshots into Brain tables", "reason": "BUILD-015 is file-backed; database persistence should follow."})
        return recs
