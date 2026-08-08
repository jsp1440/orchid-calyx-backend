from __future__ import annotations

import math

import pytest

from runtime.scientific_uncertainty import (
    SCIPY_VERSION,
    mean_confidence_interval,
    mean_confidence_interval_from_summary,
)


def test_mean_ci_matches_nist_195_observation_reference():
    # NIST/SEMATECH Dataplot CONFIDENCE LIMITS example:
    # n=195, mean=9.26146, sample sd=0.02278, 95% interval 9.25824..9.26467.
    result = mean_confidence_interval_from_summary(
        sample_size=195,
        sample_mean=9.26146,
        sample_sd=0.02278,
        confidence_level=0.95,
    )

    assert result["sample_size"] == 195
    assert result["degrees_of_freedom"] == 194
    assert math.isclose(result["critical_value"], 1.972, abs_tol=5e-4)
    assert math.isclose(result["lower"], 9.25824, abs_tol=5e-5)
    assert math.isclose(result["upper"], 9.26467, abs_tol=5e-5)
    assert result["numerical_library"] == "scipy"
    assert result["numerical_library_version"] == SCIPY_VERSION


def test_mean_ci_matches_nist_ten_observation_reference():
    # Second independent NIST table: n=10, mean=0.99800, sd=0.00434,
    # 95% interval 0.99489..1.00110.
    result = mean_confidence_interval_from_summary(
        sample_size=10,
        sample_mean=0.99800,
        sample_sd=0.00434,
        confidence_level=0.95,
    )

    assert result["degrees_of_freedom"] == 9
    assert math.isclose(result["critical_value"], 2.262, abs_tol=5e-4)
    assert math.isclose(result["lower"], 0.99489, abs_tol=5e-5)
    assert math.isclose(result["upper"], 1.00110, abs_tol=5e-5)


def test_value_wrapper_preserves_non_authority_and_no_p_value():
    result = mean_confidence_interval([1.0, 2.0, 3.0, 4.0], 0.95)

    assert result["sample_size"] == 4
    assert result["sample_mean"] == 2.5
    assert result["p_value_generated"] is False
    assert result["scientific_interpretation_generated"] is False
    assert result["human_review_required_for_scientific_conclusion"] is True
    assert result["scientific_publication_authorized"] is False
    assert result["knowledge_graph_mutation_authorized"] is False
    assert result["analysis_plan_method_registered"] is False


def test_mean_ci_fails_closed_for_invalid_sample_and_confidence_level():
    with pytest.raises(ValueError, match="UNCERTAINTY_MEAN_CI_REQUIRES_TWO_OBSERVATIONS"):
        mean_confidence_interval([1.0], 0.95)

    with pytest.raises(ValueError, match="UNCERTAINTY_CONFIDENCE_LEVEL_UNSUPPORTED"):
        mean_confidence_interval([1.0, 2.0, 3.0], 0.975)

    with pytest.raises(ValueError, match="UNCERTAINTY_MEAN_CI_SD_INVALID"):
        mean_confidence_interval_from_summary(
            sample_size=10,
            sample_mean=1.0,
            sample_sd=-1.0,
            confidence_level=0.95,
        )


def test_mean_ci_rejects_boolean_and_non_finite_inputs():
    with pytest.raises(TypeError, match="UNCERTAINTY_MEAN_CI_VALUE_INVALID"):
        mean_confidence_interval([True, 2.0], 0.95)

    with pytest.raises(ValueError, match="UNCERTAINTY_MEAN_CI_VALUE_INVALID"):
        mean_confidence_interval([1.0, float("nan")], 0.95)
