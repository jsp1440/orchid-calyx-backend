"""Test OverflowError handling in scientific transforms."""

from __future__ import annotations

import pytest

from runtime.scientific_transforms import (
    apply_transformations,
    normalize_transformations,
)


def test_overflow_in_scale_factor_raises_transform_non_finite_value():
    """Test that OverflowError from large integer scale factor is mapped to TRANSFORM_NON_FINITE_VALUE."""
    variables = [
        {"name": "value", "kind": "numeric", "unit": "1", "role": "predictor"},
    ]
    transformations = [
        {
            "operation": "scale",
            "source": "value",
            "target": "scaled_value",
            "unit": "1",
            "factor": 10**400,  # JSON big integer that overflows to float
        }
    ]
    with pytest.raises(ValueError, match="TRANSFORM_NON_FINITE_VALUE"):
        normalize_transformations(transformations, variables)


def test_overflow_in_data_value_raises_transform_non_finite_value():
    """Test that OverflowError from large integer data value is mapped to TRANSFORM_NON_FINITE_VALUE."""
    variables = [
        {"name": "value", "kind": "numeric", "unit": "1", "role": "predictor"},
    ]
    transformations = [
        {
            "operation": "scale",
            "source": "value",
            "target": "scaled_value",
            "unit": "1",
            "factor": 2.0,
        }
    ]
    normalized, _ = normalize_transformations(transformations, variables)

    rows = [
        {"value": 10**400},  # JSON big integer that overflows to float
    ]
    with pytest.raises(ValueError, match="TRANSFORM_NON_FINITE_VALUE"):
        apply_transformations(rows, normalized)


def test_non_numeric_string_still_raises_transform_non_numeric_value():
    """Test that non-numeric strings still raise TRANSFORM_NON_NUMERIC_VALUE, not TRANSFORM_NON_FINITE_VALUE."""
    variables = [
        {"name": "value", "kind": "numeric", "unit": "1", "role": "predictor"},
    ]
    transformations = [
        {
            "operation": "scale",
            "source": "value",
            "target": "scaled_value",
            "unit": "1",
            "factor": "not_a_number",
        }
    ]
    with pytest.raises(ValueError, match="TRANSFORM_NON_NUMERIC_VALUE"):
        normalize_transformations(transformations, variables)


def test_non_numeric_string_in_data_raises_transform_non_numeric_value():
    """Test that non-numeric strings in data still raise TRANSFORM_NON_NUMERIC_VALUE."""
    variables = [
        {"name": "value", "kind": "numeric", "unit": "1", "role": "predictor"},
    ]
    transformations = [
        {
            "operation": "scale",
            "source": "value",
            "target": "scaled_value",
            "unit": "1",
            "factor": 2.0,
        }
    ]
    normalized, _ = normalize_transformations(transformations, variables)

    rows = [
        {"value": "not_a_number"},
    ]
    with pytest.raises(ValueError, match="TRANSFORM_NON_NUMERIC_VALUE"):
        apply_transformations(rows, normalized)
