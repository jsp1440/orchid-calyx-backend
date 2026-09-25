"""What happened to a plant, when it happened, and when anybody wrote it down.

TWO CLOCKS, NEVER ONE

A grower notices on Sunday that a plant spiked sometime last week. The spike
happened last week; the record was made on Sunday. Storing one timestamp
destroys whichever fact it displaces, and both are needed: the first orders the
plant's biology, the second tells you how reliable the first is. An event
recorded three weeks late is a weaker claim about timing than one recorded the
same hour, and only keeping both makes that visible.

APPEND-ONLY, SO A CORRECTION IS A NEW FACT

Nothing here is ever edited. A mistaken entry is superseded by a later event
that names the one it corrects, which leaves both the error and the repair in
the record. Editing in place would silently rewrite history a grower may have
already reasoned from, and there would be no way to tell it had happened.

Superseding is not deletion. A superseded event stays readable and stays marked
as superseded, because "I thought it flowered in March and I was wrong" is
itself information about the collection.

AN OBSERVATION IS NOT EVIDENCE

Everything in this ledger is what a grower said about their own plant. That is
genuinely valuable and it is not a scientific measurement, a verified
determination, or literature. The recorder is stored on every event so that
nothing downstream can lose track of who claimed it, and no consumer may
promote these into evidence without a process that this module deliberately
does not provide.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

__all__ = [
    "EVENT_KINDS",
    "RECORDER_KINDS",
    "ConservatoryEventStore",
    "PlantEvent",
    "PlantEventError",
]

#: What a grower actually does to a plant. Each is a distinct husbandry act;
#: a generic "note" is deliberately absent, because an unclassified pile is
#: what this ledger exists to avoid.
EVENT_KINDS: frozenset[str] = frozenset(
    {
        "accessioned",
        "repotted",
        "mounted",
        "moved",
        "watered",
        "fertilised",
        "flowering_observed",
        "spike_observed",
        "leaf_observation",
        "root_observation",
        "pest_observation",
        "disease_observation",
        "treatment_applied",
        "photograph_taken",
        "died",
        "disposed",
        # A correction is itself an event, so the ledger can stay append-only.
        "correction",
    }
)

#: Who or what made the record. An automated import and a person typing are
#: different claims, and a consumer weighing reliability needs to tell them
#: apart.
RECORDER_KINDS: frozenset[str] = frozenset({"grower", "import", "system"})


class PlantEventError(ValueError):
    """Raised when an event would misrepresent what happened or who said it."""


@dataclass(frozen=True)
class PlantEvent:
    id: str
    plant_id: str
    kind: str
    #: When the thing happened in the world.
    occurred_at: str
    #: When somebody wrote it down. Never inferred from occurred_at.
    recorded_at: str
    recorder_kind: str
    recorder_ref: str | None
    note: str | None
    #: The event this one corrects, when this is a correction.
    supersedes_id: str | None
    #: Set on the event that was corrected, so both remain readable.
    superseded_by_id: str | None
    #: Free-form husbandry detail, e.g. the medium used when repotting. Kept
    #: separate from `note` so structured detail is not buried in prose.
    detail: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ConservatoryEventStore:
    """Atomic, append-only JSON ledger of plant events."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "plant_events.json"
        self._lock = Lock()

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise TypeError("conservatory event store is malformed")
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
        kind: str,
        occurred_at: str,
        recorder_kind: str = "grower",
        recorder_ref: str | None = None,
        note: str | None = None,
        supersedes_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not plant_id:
            raise PlantEventError("PLANT_REQUIRED")
        if kind not in EVENT_KINDS:
            raise PlantEventError("EVENT_KIND_UNRECOGNISED")
        if recorder_kind not in RECORDER_KINDS:
            raise PlantEventError("RECORDER_KIND_UNRECOGNISED")
        if not occurred_at:
            raise PlantEventError("OCCURRED_AT_REQUIRED")
        # A correction that does not say what it corrects is just another
        # claim, and the contradiction it creates becomes unresolvable.
        if kind == "correction" and not supersedes_id:
            raise PlantEventError("CORRECTION_REQUIRES_A_TARGET")

        now = datetime.now(UTC).isoformat()
        with self._lock:
            rows = self._read()
            target = None
            if supersedes_id is not None:
                target = next((row for row in rows if row["id"] == supersedes_id), None)
                if target is None:
                    raise PlantEventError("SUPERSEDED_EVENT_NOT_FOUND")
                if target["plant_id"] != plant_id:
                    # Correcting another plant's record would move a fact
                    # between plants with nothing marking that it happened.
                    raise PlantEventError("SUPERSEDED_EVENT_BELONGS_TO_ANOTHER_PLANT")
                if target["superseded_by_id"] is not None:
                    raise PlantEventError("EVENT_ALREADY_SUPERSEDED")

            event = PlantEvent(
                id=str(uuid4()),
                plant_id=plant_id,
                kind=kind,
                occurred_at=occurred_at,
                recorded_at=now,
                recorder_kind=recorder_kind,
                recorder_ref=(recorder_ref or "").strip() or None,
                note=(note or "").strip() or None,
                supersedes_id=supersedes_id,
                superseded_by_id=None,
                detail=dict(detail or {}),
            ).as_dict()
            if target is not None:
                # Marked, never removed: "I thought it flowered in March and I
                # was wrong" is itself information about the collection.
                target["superseded_by_id"] = event["id"]
            rows.append(event)
            self._write(rows)
            return event

    def events_for(
        self, plant_id: str, *, include_superseded: bool = True
    ) -> list[dict[str, Any]]:
        """A plant's ledger, ordered by when things happened.

        Ordered by occurrence rather than by entry, because the timeline a
        grower reasons over is the plant's, not the typist's. Entry order is
        still recoverable from recorded_at.
        """
        with self._lock:
            rows = [row for row in self._read() if row["plant_id"] == plant_id]
        if not include_superseded:
            rows = [row for row in rows if row["superseded_by_id"] is None]
        return sorted(rows, key=lambda row: (row["occurred_at"], row["recorded_at"]))

    def timeline(self, plant_id: str) -> dict[str, Any]:
        """What currently stands, and what was corrected away, kept apart."""
        everything = self.events_for(plant_id)
        standing = [row for row in everything if row["superseded_by_id"] is None]
        corrected = [row for row in everything if row["superseded_by_id"] is not None]
        return {
            "plant_id": plant_id,
            "standing": standing,
            "corrected": corrected,
            # Stated rather than left for a caller to infer from empty lists:
            # a plant with no events and a plant whose events were all
            # corrected are different situations.
            "event_count": len(everything),
            "provenance": "grower_recorded_collection_events",
            "is_scientific_evidence": False,
        }
