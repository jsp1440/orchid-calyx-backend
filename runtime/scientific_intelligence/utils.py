"""BUILD-062 shared utilities for the scientific_intelligence package.

Centralizes helpers used by multiple modules:
  - utc_now()  — current UTC timestamp as ISO-8601 string
  - to_int()   — safe int coercion with default
  - to_float() — safe float coercion with default
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def to_int(value: Any, default: int = 0) -> int:
    """Coerce *value* to int; return *default* on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def to_float(value: Any, default: float = 0.0) -> float:
    """Coerce *value* to float; return *default* on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
