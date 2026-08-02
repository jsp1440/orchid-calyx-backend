"""Immutable local staging store for World Plants release inspection reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runtime.world_plants_ingest import build_snapshot, parse_world_orchids_release


class WorldPlantsReleaseStore:
    """Persist uploaded source bytes and inspection metadata without promotion."""

    def __init__(self, root: str | Path, *, max_upload_bytes: int = 75_000_000) -> None:
        self.root = Path(root)
        self.max_upload_bytes = max_upload_bytes

    def inspect_and_store(
        self,
        payload: bytes,
        *,
        filename: str,
        version_label: str,
        acquired_at: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        if not payload:
            raise ValueError("taxonomy release file is empty")
        if len(payload) > self.max_upload_bytes:
            raise ValueError("taxonomy release file exceeds configured size limit")

        parsed = parse_world_orchids_release(payload)
        snapshot = build_snapshot(
            payload,
            version_label=version_label,
            acquired_at=acquired_at,
            filename=filename,
        )
        release_id = snapshot.sha256
        release_dir = self.root / release_id
        release_dir.mkdir(parents=True, exist_ok=True)

        source_path = release_dir / "source.bin"
        if source_path.exists() and source_path.read_bytes() != payload:
            raise RuntimeError("checksum collision detected")
        if not source_path.exists():
            source_path.write_bytes(payload)

        report = {
            "release_id": release_id,
            "state": "inspected",
            "snapshot": snapshot.as_dict(),
            "inspection": parsed.summary(),
            "issues": list(parsed.issues),
            "notes": notes,
            "canonical_promotion": "blocked_pending_staging_comparison_and_owner_approval",
            "automatic_promotion": False,
        }
        report_path = release_dir / "report.json"
        report_path.write_text(
            json.dumps(report, sort_keys=True, indent=2), encoding="utf-8"
        )
        return report

    def get(self, release_id: str) -> dict[str, Any] | None:
        report_path = self.root / release_id / "report.json"
        if not report_path.exists():
            return None
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def list_reports(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        reports = [
            report
            for child in self.root.iterdir()
            if child.is_dir() and (report := self.get(child.name)) is not None
        ]
        return sorted(
            reports,
            key=lambda item: str(item.get("snapshot", {}).get("acquired_at", "")),
            reverse=True,
        )
