"""Append-only, non-scientific Conservatory evaluation history."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from runtime.cultivated_identity import resolve_cultivated_identity

__all__ = [
    "LOCATION_KINDS",
    "RELATIONSHIPS",
    "ConservatoryEvaluationStore",
    "EvaluationError",
    "PlantEvaluation",
]

LOCATION_KINDS: frozenset[str] = frozenset(
    {
        "greenhouse",
        "shade_house",
        "lathhouse",
        "indoors",
        "outdoors",
        "windowsill",
        "grow_tent",
        "unknown",
    }
)
RELATIONSHIPS: frozenset[str] = frozenset(
    {"species", "cultivar_of_species", "cross_within_species", "none"}
)
MAX_LIST_ITEMS = 40
MAX_ITEM_CHARACTERS = 1000


class EvaluationError(ValueError):
    """Raised when an evaluation would overstate or leak what was recorded."""


@dataclass(frozen=True)
class PlantEvaluation:
    id: str
    plant_id: str
    cultivated_identity: str
    species_consulted: str | None
    relationship: str
    location_kind: str
    standing_observations: list[str]
    alternatives_considered: list[str]
    recorded_at: str
    is_scientific_evidence: bool = False
    observations_are_evidence: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise EvaluationError(code)


def _clean_items(values: list[str], *, field: str) -> list[str]:
    _require(len(values) <= MAX_LIST_ITEMS, f"{field}_TOO_MANY_ITEMS")
    cleaned: list[str] = []
    for value in values:
        _require(isinstance(value, str), f"{field}_ITEM_MUST_BE_TEXT")
        item = value.strip()
        _require(bool(item), f"{field}_ITEM_MUST_NOT_BE_EMPTY")
        _require(len(item) <= MAX_ITEM_CHARACTERS, f"{field}_ITEM_TOO_LONG")
        _require(
            not any(ord(character) <= 31 or ord(character) == 127 for character in item),
            f"{field}_ITEM_CONTAINS_CONTROL_CHARACTER",
        )
        cleaned.append(item)
    return cleaned


class ConservatoryEvaluationStore:
    """Atomic ledger where every evaluation remains independently readable."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "plant_evaluations.json"
        self._lock = Lock()

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise TypeError("conservatory evaluation store is malformed")
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
        cultivated_identity: str,
        species_consulted: str | None,
        relationship: str,
        location_kind: str,
        standing_observations: list[str],
        alternatives_considered: list[str],
    ) -> dict[str, Any]:
        _require(bool(plant_id), "PLANT_REQUIRED")
        _require(relationship in RELATIONSHIPS, "RELATIONSHIP_UNRECOGNISED")
        _require(location_kind in LOCATION_KINDS, "LOCATION_KIND_UNRECOGNISED")

        stored_identity = cultivated_identity.strip()
        resolved = resolve_cultivated_identity(stored_identity)
        _require(resolved is not None, "CULTIVATED_IDENTITY_UNSAFE")
        _require(
            relationship == resolved.relationship,
            "RELATIONSHIP_CONTRADICTS_CULTIVATED_IDENTITY",
        )
        normalized_species = (species_consulted or "").strip() or None
        _require(
            normalized_species == resolved.species,
            "SPECIES_CONTRADICTS_CULTIVATED_IDENTITY",
        )

        evaluation = PlantEvaluation(
            id=str(uuid4()),
            plant_id=plant_id,
            cultivated_identity=stored_identity,
            species_consulted=normalized_species,
            relationship=relationship,
            location_kind=location_kind,
            standing_observations=_clean_items(
                standing_observations, field="STANDING_OBSERVATIONS"
            ),
            alternatives_considered=_clean_items(
                alternatives_considered, field="ALTERNATIVES_CONSIDERED"
            ),
            recorded_at=datetime.now(UTC).isoformat(),
        ).as_dict()

        with self._lock:
            rows = self._read()
            rows.append(evaluation)
            self._write(rows)
        return evaluation

    def evaluations_for(self, plant_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [row for row in self._read() if row["plant_id"] == plant_id]

    def history(self, plant_id: str) -> dict[str, Any]:
        evaluations = self.evaluations_for(plant_id)
        return {
            "plant_id": plant_id,
            "evaluations": evaluations,
            "count": len(evaluations),
            "provenance": "grower_recorded_cultivation_evaluations",
            "is_scientific_evidence": False,
            "observations_are_evidence": False,
        }
