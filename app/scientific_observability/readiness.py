"""Calculated, explainable readiness — the ``sci-obs-readiness-v1`` contract.

Extends the canonical readiness metric shape
(``app.homepage_readiness.contracts.ReadinessMetric``:
numerator/denominator/state/limitation, ``unavailable_not_zero`` semantics)
into six explainable dimensions. This is NOT a parallel readiness authority: it
composes the same primitives and carries no publication authority.

Unknown remains unknown. A missing canonical input is ``unavailable``, never
``0`` and never fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

CALCULATION_VERSION = "sci-obs-readiness-v1"

DIMENSIONS = (
    "engineering_health",
    "integration_health",
    "data_readiness",
    "scientific_evidence_readiness",
    "product_workflow_readiness",
    "freshness",
)

COMPONENTS = (
    "taxonomy",
    "provenance",
    "occurrences",
    "traits",
    "pollinators",
    "mycorrhizae",
    "literature",
    "images",
)


class DimensionState:
    AVAILABLE = "available"
    CONDITIONAL = "conditional"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    ERROR = "error"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class DimensionScore:
    key: str
    state: str
    numerator: int | None = None
    denominator: int | None = None
    missing_requirements: list[str] = field(default_factory=list)
    upstream_blockers: list[str] = field(default_factory=list)
    limitation: str | None = None
    calculation_version: str = CALCULATION_VERSION
    measured_at: str = field(default_factory=_now)

    @property
    def score(self) -> float | None:
        """Fraction in [0,1], or ``None`` when unknown/unavailable.

        Absence never becomes zero: if the denominator is unknown/zero the
        score is ``None`` (unknown), not ``0.0``.
        """

        if self.denominator is None or self.numerator is None or self.denominator == 0:
            return None
        return round(self.numerator / self.denominator, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "state": self.state,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "score": self.score,
            "missing_requirements": list(self.missing_requirements),
            "upstream_blockers": list(self.upstream_blockers),
            "limitation": self.limitation,
            "calculation_version": self.calculation_version,
            "measured_at": self.measured_at,
        }


def component_coverage(available_components: dict[str, bool | None]) -> dict[str, dict[str, Any]]:
    """Report coverage per canonical component.

    ``available_components[name]`` is ``True`` (canonical input present),
    ``False`` (canonical input queried and absent), or ``None``/missing (never
    queried → unavailable, NOT zero).
    """

    coverage: dict[str, dict[str, Any]] = {}
    for name in COMPONENTS:
        present = available_components.get(name)
        if present is None:
            coverage[name] = {"state": DimensionState.UNAVAILABLE, "present": None}
        elif present:
            coverage[name] = {"state": DimensionState.AVAILABLE, "present": True}
        else:
            coverage[name] = {"state": DimensionState.UNKNOWN, "present": False}
    return coverage


def build_readiness(
    dimensions: dict[str, DimensionScore],
    coverage_inputs: dict[str, bool | None] | None = None,
) -> dict[str, Any]:
    """Assemble the full readiness payload for a taxon/module.

    ``overall_state`` is ``blocked`` if any dimension is blocked, ``conditional``
    if any is conditional/unavailable/unknown, else ``ready``. Absence is
    surfaced, never converted to completion.
    """

    dim_payloads = {k: dimensions[k].to_dict() for k in dimensions}
    states = {d["state"] for d in dim_payloads.values()}
    if DimensionState.BLOCKED in states or DimensionState.ERROR in states:
        overall = "blocked"
    elif states & {DimensionState.CONDITIONAL, DimensionState.UNAVAILABLE, DimensionState.UNKNOWN}:
        overall = "conditional"
    else:
        overall = "ready"

    return {
        "contract_version": CALCULATION_VERSION,
        "generated_at": _now(),
        "overall_state": overall,
        "dimensions": dim_payloads,
        "component_coverage": component_coverage(coverage_inputs or {}),
        "human_approval_required": True,
        "publication_authority": False,
    }
