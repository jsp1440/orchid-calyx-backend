"""Bounded uncertainty primitives for CALYX-617.

This module is intentionally not registered as a live Analysis Plan method yet. It
establishes the numerical/reference-value foundation required by SCICOMP-001J/K before
inferential methods are exposed through the Scientific Analysis API.
"""
from __future__ import annotations

import math
import platform
from collections.abc import Iterable
from importlib.metadata import version
from statistics import fmean, stdev
from typing import Any

from scipy.stats import t as student_t

UNCERTAINTY_SCHEMA_VERSION = "calyx-scientific-uncertainty/v1"
SUPPORTED_CONFIDENCE_LEVELS = {0.90, 0.95, 0.99}
PYTHON_IMPLEMENTATION = platform.python_implementation()
PYTHON_VERSION = platform.python_version()
NUMPY_VERSION = version("numpy")
SCIPY_VERSION = version("scipy")

MEAN_CI_CANDIDATE_METHOD: dict[str, Any] = {
    "method": "mean_ci.v1",
    "name": "Population mean confidence interval",
    "family": "uncertainty",
    "version": "1.0.0-candidate",
    "registered": False,
    "inferential": True,
    "p_value_capable": False,
    "parameters": {
        "column": "one declared numeric variable",
        "confidence_level": sorted(SUPPORTED_CONFIDENCE_LEVELS),
    },
    "missing_policy": "complete_case",
    "sidedness": "two_sided",
    "distribution": "student_t",
    "assumptions": [
        "Observations are appropriately independent for the intended inference.",
        "Population variance is unknown and estimated with the sample standard deviation.",
        "For small samples, the population distribution should be approximately normal or otherwise scientifically justified for a Student-t mean interval.",
        "The confidence level and target variable are declared before the interval is computed.",
    ],
}


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


def numerical_environment() -> dict[str, str]:
    """Return the exact numerical environment embedded into uncertainty artifacts."""
    return {
        "python_implementation": PYTHON_IMPLEMENTATION,
        "python_version": PYTHON_VERSION,
        "numpy_version": NUMPY_VERSION,
        "scipy_version": SCIPY_VERSION,
    }


def normalize_mean_ci_candidate_parameters(value: Any) -> dict[str, Any]:
    """Normalize the proposed Analysis Plan parameter contract without registering it."""
    if not isinstance(value, dict):
        raise TypeError("UNCERTAINTY_MEAN_CI_PARAMETERS_INVALID")
    extras = sorted(set(value) - {"column", "confidence_level"})
    if extras:
        raise ValueError(f"UNCERTAINTY_MEAN_CI_PARAMETERS_UNSUPPORTED:{','.join(extras)}")
    column = str(value.get("column") or "").strip()
    if not column:
        raise ValueError("UNCERTAINTY_MEAN_CI_COLUMN_REQUIRED")
    confidence_level = _finite(
        value.get("confidence_level"), "UNCERTAINTY_CONFIDENCE_LEVEL_INVALID"
    )
    if confidence_level not in SUPPORTED_CONFIDENCE_LEVELS:
        raise ValueError("UNCERTAINTY_CONFIDENCE_LEVEL_UNSUPPORTED")
    return {"column": column, "confidence_level": confidence_level}


def validate_mean_ci_candidate_variable(
    parameters: dict[str, Any], variables: list[dict[str, Any]]
) -> dict[str, Any]:
    """Require the candidate target to be a declared numeric variable with a unit."""
    column = parameters["column"]
    metadata = {
        str(item.get("name") or "").strip(): item
        for item in variables
        if isinstance(item, dict)
    }
    if column not in metadata:
        raise ValueError(f"UNCERTAINTY_MEAN_CI_VARIABLE_NOT_DECLARED:{column}")
    variable = metadata[column]
    if str(variable.get("kind") or "").strip().casefold() != "numeric":
        raise ValueError("UNCERTAINTY_MEAN_CI_VARIABLE_NOT_NUMERIC")
    unit = str(variable.get("unit") or "").strip()
    if not unit:
        raise ValueError("UNCERTAINTY_MEAN_CI_VARIABLE_UNIT_REQUIRED")
    return {
        "name": column,
        "kind": "numeric",
        "role": str(variable.get("role") or "").strip().casefold(),
        "unit": unit,
    }


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
        "numerical_environment": numerical_environment(),
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


def evaluate_mean_ci_candidate_rows(
    *,
    rows: list[dict[str, Any]],
    parameters: dict[str, Any],
    variables: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate candidate semantics on already-governed analytical rows.

    This helper does not perform project/dataset binding and is intentionally not wired
    to a router. The Research Analysis workflow must establish the final analytical row
    population before a future live method can call this contract.
    """
    normalized = normalize_mean_ci_candidate_parameters(parameters)
    variable = validate_mean_ci_candidate_variable(normalized, variables)
    values: list[float] = []
    missing = 0
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("UNCERTAINTY_MEAN_CI_ROWS_INVALID")
        raw = row.get(normalized["column"])
        if raw is None or raw == "":
            missing += 1
            continue
        values.append(_finite(raw, "UNCERTAINTY_MEAN_CI_VALUE_INVALID"))
    interval = mean_confidence_interval(values, normalized["confidence_level"])
    return {
        "method_candidate": MEAN_CI_CANDIDATE_METHOD["method"],
        "method_candidate_registered": False,
        "parameters": normalized,
        "variable": variable,
        "rows_received": len(rows),
        "complete_values": len(values),
        "missing_values": missing,
        "missing_policy": "complete_case",
        "interval": interval,
    }
