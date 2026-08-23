"""Environmental context for a growing location, and where each number came from.

THE ONE RULE THIS MODULE EXISTS TO ENFORCE

A number describing a plant's environment is only as trustworthy as its
origin, and the four origins below are not interchangeable:

    measured    a device reported it. Carries an instrument identity.
    manual      a person read a dial, or judged it. No instrument identity.
    inferred    this system derived it from something else.
    unknown     nobody has said. Not zero, not a default, not an average.

A recommendation is deliberately NOT an origin here. A recommendation is
advice about what should be true; these are claims about what was true. Storing
them in one place would let "keep it at 18C" be read later as "it was 18C".

WHY MEASURED REQUIRES AN INSTRUMENT

Without one, "measured" is just a person's assertion wearing a sensor's
authority. A reading that claims to be measured and cannot say by what is
refused outright rather than silently downgraded, because a silent downgrade
hides a caller bug while leaving the caller believing a sensor is attached.

WHY MISSING IS NOT ZERO

A greenhouse with no humidity sensor has unknown humidity, not 0% humidity.
Every absent value here stays None and is reported as absent. Filling it with a
default would put a fabricated measurement into the record that later reasoning
cannot distinguish from a real one.

WHY A READING HAS A WINDOW

"18C" is not a fact about a bench; "18C at 06:00" and "12-19C overnight" are.
A reading therefore carries either an instant or a window, and a summary over a
window is marked as a summary so nobody reads a nightly minimum as a spot
value.
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
    "ENVIRONMENT_ORIGINS",
    "MEASURABLE_VARIABLES",
    "ConservatoryEnvironmentStore",
    "EnvironmentError_",
    "EnvironmentReading",
]

#: How a number came to be known. Ordered from strongest to weakest claim.
ENVIRONMENT_ORIGINS: tuple[str, ...] = ("measured", "manual", "inferred", "unknown")

#: What can be recorded. Deliberately small: each entry has an agreed unit, and
#: a variable without one invites two growers recording different things under
#: the same name.
MEASURABLE_VARIABLES: dict[str, str] = {
    "temperature_c": "degrees Celsius",
    "relative_humidity_pct": "percent",
    "light_ppfd_umol_m2_s": "micromole per square metre per second",
    "daily_light_integral_mol_m2_d": "mole per square metre per day",
}


class EnvironmentError_(ValueError):
    """Raised when an environmental record would misrepresent its own origin."""


@dataclass(frozen=True)
class EnvironmentReading:
    id: str
    location_id: str
    variable: str
    unit: str
    #: None means nobody has said. It never means zero.
    value: float | None
    origin: str
    #: What produced it. Required for `measured`, forbidden guesswork otherwise.
    instrument: str | None
    #: What an inferred value was derived from. Required for `inferred`, so an
    #: inference can always be traced back to whatever justified it.
    derived_from: str | None
    #: A single moment, or the start of a window.
    observed_at: str
    #: End of the window when this summarises a period rather than an instant.
    window_end: str | None
    #: True when the value summarises the window rather than sampling it.
    is_summary: bool
    summary_kind: str | None
    note: str | None
    recorded_at: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


SUMMARY_KINDS: frozenset[str] = frozenset({"min", "max", "mean", "median", "range"})


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise EnvironmentError_(code)


class ConservatoryEnvironmentStore:
    """Atomic JSON store for environmental readings, append-only."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "environment.json"
        self._lock = Lock()

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise TypeError("conservatory environment store is malformed")
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
        location_id: str,
        variable: str,
        value: float | None,
        origin: str,
        observed_at: str,
        instrument: str | None = None,
        derived_from: str | None = None,
        window_end: str | None = None,
        summary_kind: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        _require(bool(location_id), "LOCATION_REQUIRED")
        _require(variable in MEASURABLE_VARIABLES, "VARIABLE_UNRECOGNISED")
        _require(origin in ENVIRONMENT_ORIGINS, "ORIGIN_UNRECOGNISED")
        _require(bool(observed_at), "OBSERVED_AT_REQUIRED")

        instrument = (instrument or "").strip() or None
        derived_from = (derived_from or "").strip() or None

        # A measurement that cannot name its instrument is an assertion wearing
        # a sensor's authority. Refused rather than downgraded, so the caller
        # learns about it instead of believing a sensor is attached.
        if origin == "measured":
            _require(instrument is not None, "MEASURED_REQUIRES_INSTRUMENT")
            _require(value is not None, "MEASURED_REQUIRES_VALUE")
        # An inference nobody can trace is indistinguishable from a guess.
        if origin == "inferred":
            _require(derived_from is not None, "INFERRED_REQUIRES_DERIVATION")
        # Only a device measures. Attaching an instrument to a hand-entered or
        # inferred value would let it be mistaken for instrumented data.
        if origin in {"manual", "inferred", "unknown"}:
            _require(instrument is None, "ONLY_MEASURED_CARRIES_AN_INSTRUMENT")
        # "Unknown" is the absence of a claim. A value would contradict it.
        if origin == "unknown":
            _require(value is None, "UNKNOWN_ORIGIN_CANNOT_CARRY_A_VALUE")

        is_summary = summary_kind is not None
        if is_summary:
            _require(summary_kind in SUMMARY_KINDS, "SUMMARY_KIND_UNRECOGNISED")
            # A summary describes a period. Without an end it is being passed
            # off as a spot reading at its start.
            _require(window_end is not None, "SUMMARY_REQUIRES_A_WINDOW")
        if window_end is not None:
            _require(window_end >= observed_at, "WINDOW_ENDS_BEFORE_IT_STARTS")

        reading = EnvironmentReading(
            id=str(uuid4()),
            location_id=location_id,
            variable=variable,
            unit=MEASURABLE_VARIABLES[variable],
            value=value,
            origin=origin,
            instrument=instrument,
            derived_from=derived_from,
            observed_at=observed_at,
            window_end=window_end,
            is_summary=is_summary,
            summary_kind=summary_kind,
            note=(note or "").strip() or None,
            recorded_at=datetime.now(UTC).isoformat(),
        ).as_dict()
        with self._lock:
            rows = self._read()
            rows.append(reading)
            self._write(rows)
        return reading

    def readings_for(
        self, location_id: str, *, variable: str | None = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = [row for row in self._read() if row["location_id"] == location_id]
        if variable is not None:
            rows = [row for row in rows if row["variable"] == variable]
        return sorted(rows, key=lambda row: row["observed_at"])

    def context_for(self, location_id: str) -> dict[str, Any]:
        """What is known about this location's environment, per variable.

        Every variable in the vocabulary appears, including the ones nobody has
        recorded. A caller comparing a plant against its location needs to see
        that humidity is unknown just as much as it needs to see the
        temperature — an absent key reads as "nothing to consider here", which
        is exactly the wrong conclusion.
        """
        rows = self.readings_for(location_id)
        context: dict[str, Any] = {}
        for variable, unit in MEASURABLE_VARIABLES.items():
            candidates = [
                row
                for row in rows
                if row["variable"] == variable and row["value"] is not None
            ]
            if not candidates:
                context[variable] = {
                    "unit": unit,
                    "known": False,
                    "origin": "unknown",
                    "reason": "NO_READING_RECORDED",
                }
                continue
            latest = candidates[-1]
            context[variable] = {
                "unit": unit,
                "known": True,
                "value": latest["value"],
                # Carried forward so a consumer can weight a hand-entered value
                # differently from an instrumented one. Never flattened away.
                "origin": latest["origin"],
                "instrument": latest["instrument"],
                "derived_from": latest["derived_from"],
                "observed_at": latest["observed_at"],
                "window_end": latest["window_end"],
                "is_summary": latest["is_summary"],
                "summary_kind": latest["summary_kind"],
            }
        return {"location_id": location_id, "variables": context}
