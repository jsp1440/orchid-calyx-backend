"""Transparent advisory ranking for SCI-OBS workflow automation opportunities.

The formula consumes only explicit classified inputs. Missing values remain
unavailable, high scientific/governance risk fails closed, and results carry no
execution, mutation, publication, or spending authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Any

FORMULA_VERSION = "automation-opportunity-ranking-v1"
HIGH_RISK_THRESHOLD = 0.75
HIGH_RISK_SCORE_CAP = 0.25


class RankingValidationError(ValueError):
    """Raised when ranking inputs are incomplete, ambiguous, or manipulated."""


class MeasurementClass(str, Enum):
    MEASURED = "MEASURED"
    CALCULATED = "CALCULATED"
    ESTIMATED = "ESTIMATED"
    UNAVAILABLE = "UNAVAILABLE"


class RankingFactor(str, Enum):
    FREQUENCY = "frequency"
    MANUAL_TIME = "manual_time"
    RETRY_REWORK_RATE = "retry_rework_rate"
    DEPENDENCY_READINESS = "dependency_readiness"
    REVERSIBILITY = "reversibility"
    SCIENTIFIC_GOVERNANCE_RISK = "scientific_governance_risk"
    DATA_COMPLETENESS = "data_completeness"


WEIGHTS: dict[RankingFactor, float] = {
    RankingFactor.FREQUENCY: 0.18,
    RankingFactor.MANUAL_TIME: 0.14,
    RankingFactor.RETRY_REWORK_RATE: 0.18,
    RankingFactor.DEPENDENCY_READINESS: 0.15,
    RankingFactor.REVERSIBILITY: 0.12,
    RankingFactor.SCIENTIFIC_GOVERNANCE_RISK: 0.10,
    RankingFactor.DATA_COMPLETENESS: 0.13,
}


@dataclass(frozen=True, slots=True)
class ClassifiedFactor:
    classification: MeasurementClass
    value: float | None
    source_ref: str | None = None

    def __post_init__(self) -> None:
        if self.classification is MeasurementClass.UNAVAILABLE:
            if self.value is not None:
                raise RankingValidationError(
                    "UNAVAILABLE factors must not contain a numeric value"
                )
            if self.source_ref is not None:
                raise RankingValidationError(
                    "UNAVAILABLE factors must not claim a source reference"
                )
            return
        if (
            isinstance(self.value, bool)
            or not isinstance(self.value, (int, float))
            or not isfinite(float(self.value))
            or not 0 <= float(self.value) <= 1
        ):
            raise RankingValidationError("factor values must be finite and normalized")
        if not self.source_ref:
            raise RankingValidationError(
                "available factors require a stable source reference"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification.value,
            "value": float(self.value) if self.value is not None else None,
            "source_ref": self.source_ref,
        }


@dataclass(frozen=True, slots=True)
class OpportunityInput:
    opportunity_id: str
    workflow_id: str
    factors: Mapping[RankingFactor, ClassifiedFactor]

    def __post_init__(self) -> None:
        for name, value in (
            ("opportunity_id", self.opportunity_id),
            ("workflow_id", self.workflow_id),
        ):
            if not value or len(value) > 120 or not all(
                character.isalnum() or character in "._:/-" for character in value
            ):
                raise RankingValidationError(f"{name} is not a bounded identifier")
        actual = set(self.factors)
        expected = set(RankingFactor)
        if actual != expected:
            raise RankingValidationError(
                "factors must use the complete closed ranking vocabulary"
            )
        if not all(isinstance(factor, ClassifiedFactor) for factor in self.factors.values()):
            raise RankingValidationError("every factor must be explicitly classified")


def _contribution(factor: RankingFactor, value: float) -> float:
    if factor is RankingFactor.SCIENTIFIC_GOVERNANCE_RISK:
        return 1 - value
    return value


def score_opportunity(opportunity: OpportunityInput) -> dict[str, Any]:
    """Score one opportunity without filling unavailable values."""

    risk = opportunity.factors[RankingFactor.SCIENTIFIC_GOVERNANCE_RISK]
    available = {
        factor: classified
        for factor, classified in opportunity.factors.items()
        if classified.classification is not MeasurementClass.UNAVAILABLE
    }
    unavailable = [
        factor.value
        for factor in RankingFactor
        if opportunity.factors[factor].classification is MeasurementClass.UNAVAILABLE
    ]

    numerator = sum(
        WEIGHTS[factor] * _contribution(factor, float(classified.value))
        for factor, classified in available.items()
        if classified.value is not None
    )
    denominator = sum(WEIGHTS[factor] for factor in available)
    score = round(numerator / denominator, 6) if denominator else None

    reason_codes: list[str] = []
    requires_human_approval = False
    if unavailable:
        reason_codes.append("INCOMPLETE_INPUTS")
    if risk.classification is MeasurementClass.UNAVAILABLE:
        score = None
        reason_codes.append("RISK_UNAVAILABLE")
        requires_human_approval = True
    elif risk.value is not None and risk.value >= HIGH_RISK_THRESHOLD:
        score = min(score, HIGH_RISK_SCORE_CAP) if score is not None else None
        reason_codes.append("HIGH_SCIENTIFIC_GOVERNANCE_RISK")
        requires_human_approval = True
    if score is None:
        reason_codes.append("NOT_RANKABLE")
    elif score >= 0.7:
        reason_codes.append("HIGH_ADVISORY_OPPORTUNITY")
    elif score >= 0.4:
        reason_codes.append("MODERATE_ADVISORY_OPPORTUNITY")
    else:
        reason_codes.append("LOW_ADVISORY_OPPORTUNITY")

    return {
        "formula_version": FORMULA_VERSION,
        "opportunity_id": opportunity.opportunity_id,
        "workflow_id": opportunity.workflow_id,
        "score": score,
        "factor_coverage": {
            "classification": MeasurementClass.CALCULATED.value,
            "available": len(available),
            "total": len(RankingFactor),
            "ratio": round(len(available) / len(RankingFactor), 6),
        },
        "factors": {
            factor.value: opportunity.factors[factor].to_dict()
            for factor in RankingFactor
        },
        "unavailable_factors": unavailable,
        "reason_codes": reason_codes,
        "requires_human_approval": requires_human_approval,
        "advisory_only": True,
        "dispatch_authority": False,
        "mutation_authority": False,
        "publication_authority": False,
        "spending_authority": False,
    }


def rank_opportunities(
    opportunities: Sequence[OpportunityInput],
) -> list[dict[str, Any]]:
    """Return deterministic score-descending order with identity tie-breaking."""

    identifiers = [opportunity.opportunity_id for opportunity in opportunities]
    if len(identifiers) != len(set(identifiers)):
        raise RankingValidationError("opportunity_id values must be unique")
    ranked = [score_opportunity(opportunity) for opportunity in opportunities]
    return sorted(
        ranked,
        key=lambda item: (
            item["score"] is None,
            -(item["score"] or 0),
            item["opportunity_id"],
        ),
    )
