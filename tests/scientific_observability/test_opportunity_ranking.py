"""WFI-001 deterministic automation-opportunity ranking tests."""

from __future__ import annotations

import pytest

from app.scientific_observability.ranking import (
    FORMULA_VERSION,
    ClassifiedFactor,
    MeasurementClass,
    OpportunityInput,
    RankingFactor,
    RankingValidationError,
    rank_opportunities,
    score_opportunity,
)


def _factor(
    value: float | None,
    classification: MeasurementClass = MeasurementClass.MEASURED,
) -> ClassifiedFactor:
    return ClassifiedFactor(
        classification=classification,
        value=value,
        source_ref=None if value is None else "event:fixture",
    )


def _opportunity(
    opportunity_id: str,
    *,
    risk: float | None = 0.2,
    unavailable: set[RankingFactor] | None = None,
) -> OpportunityInput:
    missing = unavailable or set()
    values = {
        RankingFactor.FREQUENCY: 0.8,
        RankingFactor.MANUAL_TIME: 0.6,
        RankingFactor.RETRY_REWORK_RATE: 0.7,
        RankingFactor.DEPENDENCY_READINESS: 0.9,
        RankingFactor.REVERSIBILITY: 0.9,
        RankingFactor.SCIENTIFIC_GOVERNANCE_RISK: risk,
        RankingFactor.DATA_COMPLETENESS: 0.8,
    }
    factors = {
        factor: (
            _factor(None, MeasurementClass.UNAVAILABLE)
            if factor in missing or values[factor] is None
            else _factor(values[factor])
        )
        for factor in RankingFactor
    }
    return OpportunityInput(
        opportunity_id=opportunity_id,
        workflow_id="harvest-fixture-001",
        factors=factors,
    )


def test_formula_is_versioned_repeatable_and_advisory_only():
    opportunity = _opportunity("opportunity-a")

    first = score_opportunity(opportunity)
    second = score_opportunity(opportunity)

    assert first == second
    assert first["formula_version"] == FORMULA_VERSION
    assert first["score"] == pytest.approx(0.781)
    assert first["factor_coverage"]["ratio"] == 1.0
    assert first["reason_codes"] == ["HIGH_ADVISORY_OPPORTUNITY"]
    assert first["advisory_only"] is True
    assert first["dispatch_authority"] is False
    assert first["mutation_authority"] is False
    assert first["publication_authority"] is False
    assert first["spending_authority"] is False


def test_unavailable_values_remain_none_and_are_not_scored_as_zero():
    opportunity = _opportunity(
        "opportunity-missing-time",
        unavailable={RankingFactor.MANUAL_TIME},
    )

    result = score_opportunity(opportunity)

    assert result["factors"]["manual_time"] == {
        "classification": "UNAVAILABLE",
        "value": None,
        "source_ref": None,
    }
    assert result["unavailable_factors"] == ["manual_time"]
    assert result["factor_coverage"]["available"] == 6
    assert result["factor_coverage"]["total"] == 7
    assert "INCOMPLETE_INPUTS" in result["reason_codes"]
    assert result["score"] is not None


def test_unavailable_risk_fails_closed_without_a_score():
    result = score_opportunity(_opportunity("opportunity-no-risk", risk=None))

    assert result["score"] is None
    assert result["requires_human_approval"] is True
    assert result["reason_codes"] == [
        "INCOMPLETE_INPUTS",
        "RISK_UNAVAILABLE",
        "NOT_RANKABLE",
    ]


def test_high_scientific_governance_risk_caps_score_and_requires_review():
    result = score_opportunity(_opportunity("opportunity-high-risk", risk=0.9))

    assert result["score"] <= 0.25
    assert result["requires_human_approval"] is True
    assert "HIGH_SCIENTIFIC_GOVERNANCE_RISK" in result["reason_codes"]


def test_manipulated_estimate_is_rejected():
    with pytest.raises(RankingValidationError, match="finite and normalized"):
        ClassifiedFactor(
            classification=MeasurementClass.ESTIMATED,
            value=4.2,
            source_ref="issue:632",
        )

    with pytest.raises(RankingValidationError, match="must not contain"):
        ClassifiedFactor(
            classification=MeasurementClass.UNAVAILABLE,
            value=0,
        )


def test_closed_factor_vocabulary_and_unique_ids_fail_closed():
    factors = dict(_opportunity("source").factors)
    factors.pop(RankingFactor.DATA_COMPLETENESS)
    with pytest.raises(RankingValidationError, match="complete closed"):
        OpportunityInput(
            opportunity_id="incomplete",
            workflow_id="workflow-1",
            factors=factors,
        )

    duplicate = _opportunity("duplicate")
    with pytest.raises(RankingValidationError, match="must be unique"):
        rank_opportunities([duplicate, duplicate])


def test_ties_have_deterministic_identity_order():
    ranked = rank_opportunities(
        [
            _opportunity("opportunity-z"),
            _opportunity("opportunity-a"),
            _opportunity("opportunity-m"),
        ]
    )

    assert [item["opportunity_id"] for item in ranked] == [
        "opportunity-a",
        "opportunity-m",
        "opportunity-z",
    ]
