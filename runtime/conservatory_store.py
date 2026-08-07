"""Persistent, owner-scoped personal collection store for My Conservatory."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

_ACCESSION_RE = re.compile(r"^OC-(\d{4})-(\d{4})$")


@dataclass(frozen=True)
class ConservatoryPlant:
    id: str
    accession_number: str
    display_name: str
    accepted_scientific_name: str | None
    location: str | None
    notes: str | None
    qr_identifier: str
    created_at: str
    updated_at: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ConservatoryStore:
    """Atomic JSON store suitable for a mounted persistent volume."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "plants.json"
        self._lock = Lock()

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise TypeError("conservatory store is malformed")
        return payload

    def _write(self, rows: list[dict[str, Any]]) -> None:
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(rows, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    @staticmethod
    def _next_accession(rows: list[dict[str, Any]], year: int) -> str:
        highest = 0
        for row in rows:
            match = _ACCESSION_RE.match(str(row.get("accession_number", "")))
            if match and int(match.group(1)) == year:
                highest = max(highest, int(match.group(2)))
        return f"OC-{year:04d}-{highest + 1:04d}"

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(reversed(self._read()))

    def get(self, plant_id: str) -> dict[str, Any] | None:
        with self._lock:
            return next((row for row in self._read() if row["id"] == plant_id), None)

    def create(
        self,
        *,
        display_name: str,
        accepted_scientific_name: str | None = None,
        location: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        normalized_name = display_name.strip()
        if len(normalized_name) < 2:
            raise ValueError("display_name must contain at least two characters")
        with self._lock:
            rows = self._read()
            now = datetime.now(UTC)
            plant_id = str(uuid4())
            plant = ConservatoryPlant(
                id=plant_id,
                accession_number=self._next_accession(rows, now.year),
                display_name=normalized_name,
                accepted_scientific_name=(accepted_scientific_name or "").strip()
                or None,
                location=(location or "").strip() or None,
                notes=(notes or "").strip() or None,
                qr_identifier=f"calyx:plant:{plant_id}",
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
            ).as_dict()
            rows.append(plant)
            self._write(rows)
            return plant

    def label_manifest(self, plant_ids: list[str] | None = None) -> dict[str, Any]:
        with self._lock:
            rows = self._read()
        selected = set(plant_ids or [])
        labels = [
            {
                "plant_id": row["id"],
                "accession_number": row["accession_number"],
                "display_name": row["display_name"],
                "accepted_scientific_name": row.get("accepted_scientific_name"),
                "qr_identifier": row["qr_identifier"],
            }
            for row in rows
            if not selected or row["id"] in selected
        ]
        return {
            "labels": labels,
            "count": len(labels),
            "generated_at": datetime.now(UTC).isoformat(),
            "canonical_promotion": "not_applicable",
        }
