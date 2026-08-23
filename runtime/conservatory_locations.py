"""Growing locations, and the history of where a plant has actually been.

WHY A LOCATION IS NOT A STRING

An accession today records `location` as free text. That is enough to print on
a label and useless for the question a grower actually asks: *where in my
collection should this plant live?* Answering that means comparing a taxon's
requirements against the real character of a bench, a windowsill, a shade
house — so a location has to be a thing with properties, not a spelling.

It also means the same bench spelled three ways ("GH bench 2", "greenhouse
bench 2", "Bench 2") is three benches, and no comparison across them is
possible.

WHY PLACEMENT IS A HISTORY, NOT A FIELD

Moving a plant is the single most informative husbandry act a grower performs,
and overwriting a `location` field destroys exactly the record that explains
what happened next. "It started spiking six weeks after it moved to the cooler
bench" is only recoverable if the move was recorded as an event with a time.

So placement is an append-only log. The current location is derived from it
rather than stored beside it, because a stored current-location can disagree
with its own history and there is then no way to tell which is wrong.

WHAT THIS DELIBERATELY DOES NOT DO

It records environment as the grower *described* it, and marks it as such.
A grower writing "bright shade" is a grower's assessment, not a measurement,
and it must never be readable later as though a sensor produced it. Actual
measurements are a separate contract with a separate origin, not yet built.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

__all__ = [
    "ConservatoryLocationStore",
    "GrowingLocation",
    "LocationChange",
    "LocationError",
    "PlacementEvent",
]

#: The kinds of place a grower actually keeps orchids. `custom` exists so the
#: vocabulary never blocks a real collection; it is not a dumping ground, and
#: the grower's own label is kept alongside it.
LOCATION_KINDS: frozenset[str] = frozenset(
    {
        "greenhouse",
        # A bench is where a plant actually sits, and two benches in one
        # greenhouse can differ more than two greenhouses do. Recording only
        # the building loses the distinction a grower is actually managing.
        "greenhouse_bench",
        "shade_house",
        "lath_house",
        "outdoor",
        "windowsill",
        "indoor_growing_area",
        "shelf",
        "zone",
        "custom",
    }
)


class LocationError(ValueError):
    """Raised when a location or placement contract would be violated."""


@dataclass(frozen=True)
class GrowingLocation:
    id: str
    name: str
    kind: str
    #: The grower's own words about conditions here. An assessment, never a
    #: measurement — see `described_by` below.
    described_conditions: str | None
    notes: str | None
    created_at: str
    #: When the grower stopped using this place, or None while it is in use.
    #: Retired rather than deleted: placement history points at this location,
    #: and deleting it would leave that history pointing at nothing — which
    #: reads as data loss rather than as a bench that was dismantled.
    retired_at: str | None = None
    retired_reason: str | None = None
    #: Always "grower_description". Carried explicitly rather than implied, so
    #: a later reader cannot mistake this for sensor-derived data. When real
    #: measurements arrive they arrive under a different origin, not by
    #: quietly reusing this field.
    described_by: str = "grower_description"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlacementEvent:
    id: str
    plant_id: str
    location_id: str | None
    #: Why the record changed. A correction is not a move: a plant wrongly
    #: entered as being on the wrong bench never physically went anywhere, and
    #: treating that as a move would invent husbandry history that did not
    #: happen.
    reason: str
    note: str | None
    recorded_at: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


PLACEMENT_REASONS: frozenset[str] = frozenset(
    {"initial", "move", "correction", "removed"}
)


@dataclass(frozen=True)
class LocationChange:
    """A change to the location itself, not to any plant standing in it.

    Renaming a bench and moving a plant off it are completely different facts,
    and both change what a grower sees next to that plant. Keeping them in one
    log would make "Bench 2 became the cool bench" indistinguishable from "the
    plant went to the cool bench", and only one of those is husbandry.
    """

    id: str
    location_id: str
    change: str
    previous_name: str | None
    new_name: str | None
    note: str | None
    recorded_at: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


LOCATION_CHANGES: frozenset[str] = frozenset(
    {"created", "renamed", "retired", "unretired"}
)


@dataclass
class _State:
    locations: list[dict[str, Any]] = field(default_factory=list)
    placements: list[dict[str, Any]] = field(default_factory=list)
    location_changes: list[dict[str, Any]] = field(default_factory=list)


class ConservatoryLocationStore:
    """Atomic JSON store for locations and the append-only placement log."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "locations.json"
        self._lock = Lock()

    def _read(self) -> _State:
        if not self.path.exists():
            return _State()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("conservatory location store is malformed")
        return _State(
            locations=list(payload.get("locations") or []),
            placements=list(payload.get("placements") or []),
            location_changes=list(payload.get("location_changes") or []),
        )

    def _write(self, state: _State) -> None:
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                {
                    "locations": state.locations,
                    "placements": state.placements,
                    "location_changes": state.location_changes,
                },
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    # ----- locations -------------------------------------------------

    def create_location(
        self,
        *,
        name: str,
        kind: str,
        described_conditions: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        normalized = (name or "").strip()
        if len(normalized) < 2:
            raise LocationError("LOCATION_NAME_TOO_SHORT")
        if kind not in LOCATION_KINDS:
            raise LocationError("LOCATION_KIND_UNRECOGNISED")
        with self._lock:
            state = self._read()
            # Names are compared case-insensitively so one bench cannot become
            # three through capitalisation, which would make every
            # cross-location comparison silently wrong.
            if any(
                row["name"].strip().lower() == normalized.lower()
                for row in state.locations
            ):
                raise LocationError("LOCATION_NAME_ALREADY_USED")
            location = GrowingLocation(
                id=str(uuid4()),
                name=normalized,
                kind=kind,
                described_conditions=(described_conditions or "").strip() or None,
                notes=(notes or "").strip() or None,
                created_at=datetime.now(UTC).isoformat(),
            ).as_dict()
            state.locations.append(location)
            state.location_changes.append(
                LocationChange(
                    id=str(uuid4()),
                    location_id=location["id"],
                    change="created",
                    previous_name=None,
                    new_name=location["name"],
                    note=None,
                    recorded_at=location["created_at"],
                ).as_dict()
            )
            self._write(state)
            return location

    def list_locations(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._read().locations)

    def get_location(self, location_id: str) -> dict[str, Any] | None:
        with self._lock:
            return next(
                (row for row in self._read().locations if row["id"] == location_id),
                None,
            )

    def rename_location(
        self, location_id: str, *, name: str, note: str | None = None
    ) -> dict[str, Any]:
        """Change what a location is called, keeping what it is.

        The id never changes, so every placement that ever pointed here still
        points here. A rename is emphatically not a move: no plant went
        anywhere, and nothing may be appended to any plant's placement history
        because of it. Recording it as a move would invent husbandry that never
        happened and would show up later as a cause of whatever the plant did
        next.
        """
        normalized = (name or "").strip()
        if len(normalized) < 2:
            raise LocationError("LOCATION_NAME_TOO_SHORT")
        with self._lock:
            state = self._read()
            target = next(
                (row for row in state.locations if row["id"] == location_id), None
            )
            if target is None:
                raise LocationError("LOCATION_NOT_FOUND")
            if any(
                row["id"] != location_id
                and row["name"].strip().lower() == normalized.lower()
                for row in state.locations
            ):
                raise LocationError("LOCATION_NAME_ALREADY_USED")
            previous = target["name"]
            if (
                previous.strip().lower() == normalized.lower()
                and previous == normalized
            ):
                # Nothing changed. Appending a rename event would put a change
                # in the log that never happened.
                return dict(target)
            target["name"] = normalized
            state.location_changes.append(
                LocationChange(
                    id=str(uuid4()),
                    location_id=location_id,
                    change="renamed",
                    previous_name=previous,
                    new_name=normalized,
                    note=(note or "").strip() or None,
                    recorded_at=datetime.now(UTC).isoformat(),
                ).as_dict()
            )
            self._write(state)
            return dict(target)

    def retire_location(
        self, location_id: str, *, reason: str | None = None
    ) -> dict[str, Any]:
        """Take a location out of use without erasing it.

        Retired rather than deleted, because placement history points here.
        Deleting the bench would leave a plant's history referring to nothing,
        which a later reader cannot distinguish from data loss — whereas a
        retired bench correctly says "this plant was there, and that place is
        gone now".
        """
        with self._lock:
            state = self._read()
            target = next(
                (row for row in state.locations if row["id"] == location_id), None
            )
            if target is None:
                raise LocationError("LOCATION_NOT_FOUND")
            if target.get("retired_at"):
                raise LocationError("LOCATION_ALREADY_RETIRED")
            occupants = self._occupancy_from(state).get(location_id, [])
            if occupants:
                # Retiring an occupied bench would strand plants in a place
                # that no longer accepts them, and nothing would say where they
                # actually are.
                raise LocationError("LOCATION_STILL_OCCUPIED")
            now = datetime.now(UTC).isoformat()
            target["retired_at"] = now
            target["retired_reason"] = (reason or "").strip() or None
            state.location_changes.append(
                LocationChange(
                    id=str(uuid4()),
                    location_id=location_id,
                    change="retired",
                    previous_name=target["name"],
                    new_name=target["name"],
                    note=target["retired_reason"],
                    recorded_at=now,
                ).as_dict()
            )
            self._write(state)
            return dict(target)

    def unretire_location(self, location_id: str) -> dict[str, Any]:
        """Bring a retired location back into use.

        Benches get dismantled and rebuilt, and a shade house closed for a
        winter reopens in spring. Without this the only way back is a second
        location with the same purpose, which splits one place's history in two
        and makes every comparison across it wrong.

        The identity is unchanged, so placements recorded before the retirement
        still point here and the plant's earlier time on this bench remains one
        continuous record rather than two unrelated ones.
        """
        with self._lock:
            state = self._read()
            target = next(
                (row for row in state.locations if row["id"] == location_id), None
            )
            if target is None:
                raise LocationError("LOCATION_NOT_FOUND")
            if not target.get("retired_at"):
                # Un-retiring something in use would append a change that never
                # happened, and the log is meant to be a record of real events.
                raise LocationError("LOCATION_NOT_RETIRED")
            target["retired_at"] = None
            target["retired_reason"] = None
            state.location_changes.append(
                LocationChange(
                    id=str(uuid4()),
                    location_id=location_id,
                    change="unretired",
                    previous_name=target["name"],
                    new_name=target["name"],
                    note=None,
                    recorded_at=datetime.now(UTC).isoformat(),
                ).as_dict()
            )
            self._write(state)
            return dict(target)

    def location_history(self, location_id: str) -> list[dict[str, Any]]:
        """Everything that happened to this location, oldest first."""
        with self._lock:
            changes = [
                row
                for row in self._read().location_changes
                if row["location_id"] == location_id
            ]
        return sorted(changes, key=lambda row: row["recorded_at"])

    # ----- placement -------------------------------------------------

    def record_placement(
        self,
        *,
        plant_id: str,
        location_id: str | None,
        reason: str = "move",
        note: str | None = None,
    ) -> dict[str, Any]:
        """Append a placement event. Never rewrites an earlier one."""
        if not plant_id:
            raise LocationError("PLANT_REQUIRED")
        if reason not in PLACEMENT_REASONS:
            raise LocationError("PLACEMENT_REASON_UNRECOGNISED")
        if location_id is None and reason != "removed":
            raise LocationError("LOCATION_REQUIRED")
        with self._lock:
            state = self._read()
            target = (
                next((row for row in state.locations if row["id"] == location_id), None)
                if location_id is not None
                else None
            )
            if location_id is not None and target is None:
                # Placing a plant somewhere that does not exist would produce a
                # history pointing at nothing, which reads as data loss later.
                raise LocationError("LOCATION_NOT_FOUND")
            if (
                target is not None
                and target.get("retired_at")
                and reason != "correction"
            ):
                # A retired place accepts no new arrivals, but a correction to
                # a past record may still name it: the plant really was there,
                # and refusing to say so would force a false history.
                raise LocationError("LOCATION_RETIRED")
            event = PlacementEvent(
                id=str(uuid4()),
                plant_id=plant_id,
                location_id=location_id,
                reason=reason,
                note=(note or "").strip() or None,
                recorded_at=datetime.now(UTC).isoformat(),
            ).as_dict()
            state.placements.append(event)
            self._write(state)
            return event

    def placement_history(self, plant_id: str) -> list[dict[str, Any]]:
        """Every recorded placement for a plant, oldest first."""
        with self._lock:
            events = [
                row for row in self._read().placements if row["plant_id"] == plant_id
            ]
        return sorted(events, key=lambda row: row["recorded_at"])

    def current_placement(self, plant_id: str) -> dict[str, Any] | None:
        """Where the plant is now, derived from its history.

        Derived rather than stored: a stored current-location can disagree with
        the log it is supposed to summarise, and nothing then says which is
        right. A plant recorded as removed is not anywhere, which is a
        different answer from never having been placed.
        """
        history = self.placement_history(plant_id)
        if not history:
            return None
        latest = history[-1]
        return None if latest["reason"] == "removed" else latest

    def occupancy(self) -> dict[str, list[str]]:
        """Plant ids currently in each location, keyed by location id."""
        with self._lock:
            state = self._read()
        return self._occupancy_from(state)

    @staticmethod
    def _occupancy_from(state: _State) -> dict[str, list[str]]:
        """Shared so retirement and the occupancy view can never disagree."""
        by_plant: dict[str, dict[str, Any]] = {}
        for event in sorted(state.placements, key=lambda row: row["recorded_at"]):
            by_plant[event["plant_id"]] = event
        result: dict[str, list[str]] = {row["id"]: [] for row in state.locations}
        for plant_id, event in by_plant.items():
            if event["reason"] == "removed" or event["location_id"] is None:
                continue
            result.setdefault(event["location_id"], []).append(plant_id)
        return {key: sorted(value) for key, value in result.items()}
