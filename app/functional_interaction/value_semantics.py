"""Deterministic comparison of extracted values before anything is called a conflict.

Two claims about the same taxon and predicate are a *contradiction* only when
they make mutually exclusive categorical statements. Everything else that
differs is recorded with a more precise, non-conflict classification:

* values that differ only in case, hyphenation or spacing are the same value;
* length measurements are compared in millimetres as exact decimals, so
  ``3 cm`` equals ``30 mm``; other units are compared case-sensitively;
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
import unicodedata
from collections.abc import Iterable
from decimal import Decimal
from typing import Literal

#: Predicates whose values co-occur rather than exclude each other.
MULTI_VALUED_PREDICATES = frozenset({"ecological_relationship", "has_trait"})

#: Length units normalized to millimetres for comparison, as exact decimals.
#: Units are matched case-sensitively after NFKC (which maps the micro sign
#: U+00B5 to Greek mu U+03BC): "mM" is millimolar, not millimetres.
LENGTH_TO_MM = {
    "mm": Decimal(1),
    "cm": Decimal(10),
    "m": Decimal(1000),
    "um": Decimal("0.001"),
    "\u03bcm": Decimal("0.001"),
}

AGREEMENT = "AGREEMENT"
CONTRADICTION = "CONTRADICTION"
VARIATION_AT_UNSTATED_LEVEL = "VARIATION_AT_UNSTATED_LEVEL"
MULTIPLE_VALUES_PERMITTED = "MULTIPLE_VALUES_PERMITTED"
INCOMMENSURABLE_VALUES = "INCOMMENSURABLE_VALUES"
INCOMMENSURABLE_UNITS = "INCOMMENSURABLE_UNITS"

#: ("measure", exact decimal string, unit) or ("categorical", normalized text).
ValueKey = tuple[Literal["categorical"], str] | tuple[Literal["measure"], str, str]

_SEPARATORS = re.compile(r"[\s_\-]+")


def normalize_categorical(value: str) -> str:
    return _SEPARATORS.sub(
        " ", unicodedata.normalize("NFKC", str(value)).casefold()
    ).strip()


def normalize_unit(unit: str | None) -> str:
    return _SEPARATORS.sub("", unicodedata.normalize("NFKC", unit or ""))


def value_key(
    *, object_value: str | None, numeric_value: float | None, unit: str | None
) -> ValueKey:
    """Comparison key for one extracted value; measurements win over text.

    Measurements are exact decimals (``Decimal(str(value))``), never rounded,
    so distinct values never merge. A non-finite measurement is refused.
    """

    if numeric_value is not None:
        number = Decimal(str(numeric_value))
        if not number.is_finite():
            raise ValueError(f"NON_FINITE_MEASUREMENT:{numeric_value}")
        unit_norm = normalize_unit(unit)
        factor = LENGTH_TO_MM.get(unit_norm)
        if factor is not None:
            number, unit_norm = number * factor, "mm"
        return ("measure", _exact(number), unit_norm)
    return ("categorical", normalize_categorical(object_value or ""))


def _exact(number: Decimal) -> str:
    text = format(number.normalize(), "f")
    return "0" if text in {"-0", "0"} else text


def display(key: ValueKey) -> str:
    if key[0] == "measure":
        return f"{key[1]} {key[2]}".strip()
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
