"""Deterministic comparison of extracted values before anything is called a conflict.

Two claims about the same taxon and predicate are a *contradiction* only when
they make mutually exclusive categorical statements. Everything else that
differs is recorded with a more precise, non-conflict classification:

* values that differ only in case, hyphenation or spacing are the same value;
* length measurements are compared in millimetres, so ``3 cm`` equals ``30 mm``;
* different measurements at an unstated assertion level are variation between
  specimens, not conflict (Brain TraitBank #246 assertion-level rule);
* predicates that legitimately hold several values at once (pollinators,
  associated organisms, generic traits) report multiple values, not conflict;
* a measurement next to a categorical value, or measurements in incommensurable
  units, cannot be compared and are reported as such.

No value is altered or dropped: callers keep the original strings for
provenance and use these keys only for comparison.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

#: Predicates whose values co-occur rather than exclude each other.
MULTI_VALUED_PREDICATES = frozenset({"ecological_relationship", "has_trait"})

#: Length units normalized to millimetres for comparison.
LENGTH_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "um": 0.001, "µm": 0.001}

AGREEMENT = "AGREEMENT"
CONTRADICTION = "CONTRADICTION"
VARIATION_AT_UNSTATED_LEVEL = "VARIATION_AT_UNSTATED_LEVEL"
MULTIPLE_VALUES_PERMITTED = "MULTIPLE_VALUES_PERMITTED"
INCOMMENSURABLE_VALUES = "INCOMMENSURABLE_VALUES"
INCOMMENSURABLE_UNITS = "INCOMMENSURABLE_UNITS"

ValueKey = tuple[Literal["categorical"], str] | tuple[Literal["measure"], float, str]

_SEPARATORS = re.compile(r"[\s_\-]+")


def normalize_categorical(value: str) -> str:
    return _SEPARATORS.sub(" ", str(value).casefold()).strip()


def value_key(
    *, object_value: str | None, numeric_value: float | None, unit: str | None
) -> ValueKey:
    """Comparison key for one extracted value; measurements win over text."""

    if numeric_value is not None:
        unit_norm = normalize_categorical(unit or "")
        factor = LENGTH_TO_MM.get(unit_norm)
        if factor is not None:
            return ("measure", round(float(numeric_value) * factor, 6), "mm")
        return ("measure", round(float(numeric_value), 6), unit_norm)
    return ("categorical", normalize_categorical(object_value or ""))


def display(key: ValueKey) -> str:
    if key[0] == "measure":
        return f"{key[1]:g} {key[2]}".strip()
    return key[1]


def classify(predicate: str, keys: Iterable[ValueKey]) -> str:
    distinct = set(keys)
    if len(distinct) <= 1:
        return AGREEMENT
    kinds = {key[0] for key in distinct}
    if len(kinds) > 1:
        return INCOMMENSURABLE_VALUES
    if kinds == {"measure"}:
        units = {key[2] for key in distinct}
        return INCOMMENSURABLE_UNITS if len(units) > 1 else VARIATION_AT_UNSTATED_LEVEL
    if predicate in MULTI_VALUED_PREDICATES:
        return MULTIPLE_VALUES_PERMITTED
    return CONTRADICTION
