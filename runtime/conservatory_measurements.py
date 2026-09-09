"""Append-only grower measurement ledger for Conservatory plants.

Measurements remain private collection records. They are useful observations, but
this store never promotes them to scientific evidence or silently converts the
unit written by the grower.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

__all__ = [
    "MEASUREMENT_METHODS",
    "TRAIT_UNITS",
    "ConservatoryMeasurementStore",
    "MeasurementError",
    "PlantMeasurement",
]

TRAIT_UNITS: dict[str, frozenset[str]] = {
    "plant_height": frozenset({"mm", "cm", "in"}),
    "leaf_length": frozenset({"mm", "cm", "in"}),
    "leaf_width": frozenset({"mm", "cm", "in"}),
    "inflorescence_height": frozenset({"mm", "cm", "in"}),
    "flower_horizontal_span": frozenset({"mm", "cm", "in"}),
    "flower_vertical_span": frozenset({"mm", "cm", "in"}),
    "pouch_height": frozenset({"mm", "cm", "in"}),
    "pouch_width": frozenset({"mm", "cm", "in"}),
    "petal_length": frozenset({"mm", "cm", "in"}),
    "petal_width": frozenset({"mm", "cm", "in"}),
    "flower_count": frozenset({"count"}),
}

MEASUREMENT_METHODS: frozenset[str] = frozenset(
    {"ruler", "caliper", "measuring_tape", "manual_count"}
)


class MeasurementError(ValueError):
    """Raised when a measurement would make the ledger misleading."""


@dataclass(frozen=True)
class PlantMeasurement:
    id: str
    plant_id: str
    trait: str
    value: float
    unit: str
    method: str
    observed_at: str
    recorded_at: str
    note: str | None
    flowering_event_id: str | None
    photograph_id: str | None
    supersedes_id: str | None
    superseded_by_id: str | None
    is_scientific_evidence: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise MeasurementError(code)


class ConservatoryMeasurementStore:
    """Atomic JSON ledger that only appends measurements and corrections."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "plant_measurements.json"
        self._lock = Lock()

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise TypeError("conservatory measurement store is malformed")
        return payload

    def _write(self, rows: list[dict[str, Any]]) -> None:
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(rows, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def record(
        self,
        *,
        plant_id: str,
        trait: str,
        value: float,
        unit: str,
        method: str,
        observed_at: str,
        note: str | None = None,
        flowering_event_id: str | None = None,
        photograph_id: str | None = None,
        supersedes_id: str | None = None,
    ) -> dict[str, Any]:
        _require(bool(plant_id), "PLANT_REQUIRED")
        _require(trait in TRAIT_UNITS, "TRAIT_UNRECOGNISED")
        _require(unit in TRAIT_UNITS[trait], "UNIT_NOT_ALLOWED_FOR_TRAIT")
        _require(method in MEASUREMENT_METHODS, "METHOD_UNRECOGNISED")
        _require(bool(observed_at), "OBSERVED_AT_REQUIRED")
        numeric_value = float(value)
        _require(math.isfinite(numeric_value), "VALUE_MUST_BE_FINITE")
        _require(numeric_value >= 0, "VALUE_MUST_NOT_BE_NEGATIVE")
        if trait == "flower_count":
            _require(method == "manual_count", "COUNT_REQUIRES_MANUAL_COUNT")
            _require(numeric_value.is_integer(), "COUNT_MUST_BE_AN_INTEGER")
        else:
            _require(method != "manual_count", "MANUAL_COUNT_REQUIRES_COUNT_TRAIT")

        measurement = PlantMeasurement(
            id=str(uuid4()),
            plant_id=plant_id,
            trait=trait,
            value=numeric_value,
            unit=unit,
            method=method,
            observed_at=observed_at,
            recorded_at=datetime.now(UTC).isoformat(),
            note=(note or "").strip() or None,
            flowering_event_id=(flowering_event_id or "").strip() or None,
            photograph_id=(photograph_id or "").strip() or None,
            supersedes_id=supersedes_id,
            superseded_by_id=None,
        ).as_dict()

        with self._lock:
            rows = self._read()
            if supersedes_id is not None:
                target = next(
                    (row for row in rows if row["id"] == supersedes_id), None
                )
                _require(target is not None, "SUPERSEDED_MEASUREMENT_NOT_FOUND")
                _require(
                    target["plant_id"] == plant_id,
                    "SUPERSEDED_MEASUREMENT_BELONGS_TO_ANOTHER_PLANT",
                )
                _require(
                    target["trait"] == trait,
                    "CORRECTION_MUST_KEEP_THE_TRAIT",
                )
                _require(
                    target.get("superseded_by_id") is None,
                    "MEASUREMENT_ALREADY_SUPERSEDED",
                )
                target["superseded_by_id"] = measurement["id"]
            rows.append(measurement)
            self._write(rows)
        return measurement

    def measurements_for(self, plant_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = [row for row in self._read() if row["plant_id"] == plant_id]
        return sorted(rows, key=lambda row: (row["observed_at"], row["recorded_at"]))

    def ledger(self, plant_id: str) -> dict[str, Any]:
        measurements = self.measurements_for(plant_id)
        return {
            "plant_id": plant_id,
            "measurements": measurements,
            "count": len(measurements),
            "standing_count": sum(
                row.get("superseded_by_id") is None for row in measurements
            ),
            "provenance": "grower_recorded_measurements",
            "is_scientific_evidence": False,
        }
