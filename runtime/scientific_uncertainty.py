"""Bounded uncertainty primitives for CALYX-617.

This module is intentionally not registered as a live Analysis Plan method yet. It
establishes the numerical/reference-value foundation required by SCICOMP-001J/K before
inferential methods are exposed through the Scientific Analysis API.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from importlib.metadata import version
from statistics import fmean, stdev
from typing import Any

from scipy.stats import t as student_t

UNCERTAINTY_SCHEMA_VERSION = "calyx-scientific-uncertainty/v1"
SUPPORTED_CONFIDENCE_LEVELS = {0.90, 0.95, 0.99}
SCIPY_VERSION = version("scipy")


def _finite(value: Any, error: str) -> float:
    if isinstance(value, bool):
        raise TypeError(error)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(error) from exc
    if not math.isfinite(number):
        raise ValueError(error)
    return number


def mean_confidence_interval_from_summary(
    *,
    sample_size: int,
    sample_mean: float,
    sample_sd: float,
    confidence_level: float,
) -> dict[str, Any]:
    """Return a classical two-sided Student-t interval for a population mean.

    The caller must declare the confidence level before execution. This primitive does
    not calculate a p-value, choose a level from the observed data, or interpret whether
    the interval supports a scientific claim.
    """
    if isinstance(sample_size, bool) or not isinstance(sample_size, int) or sample_size < 2:
        raise ValueError("UNCERTAINTY_MEAN_CI_REQUIRES_TWO_OBSERVATIONS")
    mean = _finite(sample_mean, "UNCERTAINTY_MEAN_CI_MEAN_INVALID")
    sample_standard_deviation = _finite(sample_sd, "UNCERTAINTY_MEAN_CI_SD_INVALID")
    if sample_standard_deviation < 0:
        raise ValueError("UNCERTAINTY_MEAN_CI_SD_INVALID")
    level = _finite(confidence_level, "UNCERTAINTY_CONFIDENCE_LEVEL_INVALID")
    if level not in SUPPORTED_CONFIDENCE_LEVELS:
        raise ValueError("UNCERTAINTY_CONFIDENCE_LEVEL_UNSUPPORTED")

    degrees_of_freedom = sample_size - 1
    standard_error = sample_standard_deviation / math.sqrt(sample_size)
    critical_value = float(student_t.ppf((1.0 + level) / 2.0, degrees_of_freedom))
    if not math.isfinite(critical_value):  # pragma: no cover - SciPy contract guard
        raise ValueError("UNCERTAINTY_T_CRITICAL_VALUE_INVALID")
    margin = critical_value * standard_error

    return {
        "schema_version": UNCERTAINTY_SCHEMA_VERSION,
        "estimand": "population_mean",
        "sample_size": sample_size,
        "sample_mean": mean,
        "sample_sd": sample_standard_deviation,
        "standard_error": standard_error,
        "confidence_level": level,
        "sidedness": "two_sided",
        "distribution": "student_t",
        "degrees_of_freedom": degrees_of_freedom,
        "critical_value": critical_value,
        "lower": mean - margin,
        "upper": mean + margin,
        "numerical_library": "scipy",
        "numerical_library_version": SCIPY_VERSION,
        "reference_formula": "mean_plus_minus_student_t_times_sample_standard_error",
        "p_value_generated": False,
        "scientific_interpretation_generated": False,
        "human_review_required_for_scientific_conclusion": True,
        "scientific_publication_authorized": False,
        "knowledge_graph_mutation_authorized": False,
        "analysis_plan_method_registered": False,
    }


def mean_confidence_interval(values: Iterable[Any], confidence_level: float) -> dict[str, Any]:
    """Compute summary statistics and delegate to the governed summary primitive."""
    numeric = [_finite(value, "UNCERTAINTY_MEAN_CI_VALUE_INVALID") for value in values]
    if len(numeric) < 2:
        raise ValueError("UNCERTAINTY_MEAN_CI_REQUIRES_TWO_OBSERVATIONS")
    return mean_confidence_interval_from_summary(
        sample_size=len(numeric),
        sample_mean=fmean(numeric),
        sample_sd=stdev(numeric),
        confidence_level=confidence_level,
    )
