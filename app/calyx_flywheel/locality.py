"""Sensitive-locality enforcement for flywheel contracts.

Protected locality is the one class of data where a leak cannot be undone. A
coordinate that reaches a log, a serialized payload or a suggestion body has
been disclosed, and no later review removes it from wherever it was read.

So the check runs at construction *and* again at serialization. Construction
alone is not enough: a payload assembled after the fact, or a dict handed
straight to a response, never passes through a constructor. Belt and braces is
the correct posture here, not redundancy.

The check fails closed and loudly. It does not redact silently — a caller who
tried to put a coordinate into a governed contract has a bug, and quietly
dropping the field would hide it while leaving the caller believing the value
travelled.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

__all__ = [
    "SENSITIVE_LOCALITY_FIELDS",
    "SensitiveLocalityError",
    "assert_no_sensitive_locality",
]


class SensitiveLocalityError(ValueError):
    """Raised when protected locality would cross a governed boundary."""


#: Field names that carry protected locality. Matching is case-insensitive and
#: applied to whole keys, so an unrelated key such as ``localization`` is not
#: caught while ``verbatimLocality`` is.
SENSITIVE_LOCALITY_FIELDS: frozenset[str] = frozenset(
    {
        "lat",
        "latitude",
        "decimal_latitude",
        "decimallatitude",
        "lon",
        "lng",
        "longitude",
        "decimal_longitude",
        "decimallongitude",
        "coord",
        "coords",
        "coordinate",
        "coordinates",
        "coordinate_uncertainty",
        "coordinate_uncertainty_in_meters",
        "locality",
        "verbatim_locality",
        "verbatimlocality",
        "location",
        "site",
        "place",
        "grid",
        "gps",
        "elevation_m",
        "elevation_meters",
        "footprint_wkt",
        "geohash",
        "occurrence_id",
        "occurrenceid",
        "catalog_number",
        "catalogue_number",
        "collector",
        "recorded_by",
        "recordedby",
    }
)


def _normalise(key: Any) -> str:
    return str(key).strip().lower()


def assert_no_sensitive_locality(payload: Any, *, path: str = "") -> None:
    """Fail closed if ``payload`` carries protected locality anywhere within it.

    Walks nested mappings and sequences, because a coordinate buried three
    levels down in a metadata blob is disclosed exactly as thoroughly as one at
    the top level.

    Only *keys* are inspected. Inspecting values would mean guessing whether a
    number is a latitude, which produces false positives on real measurements
    (a confidence of 0.5, an elevation-free trait value) and false negatives on
    anything stringified. The contract is that protected locality travels under
    a known field name; anything else is a different problem needing a
    different control.
    """
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            normalised = _normalise(key)
            if normalised in SENSITIVE_LOCALITY_FIELDS:
                where = f"{path}.{key}" if path else str(key)
                raise SensitiveLocalityError(
                    f"SENSITIVE_LOCALITY_FORBIDDEN: {where}"
                )
            assert_no_sensitive_locality(value, path=f"{path}.{key}" if path else str(key))
        return

    if isinstance(payload, (str, bytes)):
        # A string is a leaf. Scanning its text for coordinates is the value
        # inspection ruled out above.
        return

    if isinstance(payload, Iterable):
        for index, item in enumerate(payload):
            assert_no_sensitive_locality(item, path=f"{path}[{index}]")
