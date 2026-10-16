"""Tests for overflow error handling in scientific filters.

Ensures that out-of-range integers that cause OverflowError during float()
conversion are properly caught and converted to appropriate ValueError codes.
"""
from __future__ import annotations

import pytest

from runtime.scientific_filters import apply_filters, normalize_filters


def _variables():
    """Standard numeric variables for testing."""
    return [
        {"name": "measurement", "kind": "numeric", "unit": "unit", "role": "predictor"},
    ]


def test_normalize_filters_with_overflow_rule_value():
    """Test that out-of-range rule values raise the correct error code."""
    variables = _variables()
    filters = [
        {
            "variable": "measurement",
            "operator": "gte",
            "value": 10**400,
            "reason_code": "TEST_REASON",
        }
    ]
    with pytest.raises(ValueError, match="ANALYSIS_ROW_FILTER_NUMERIC_VALUE_INVALID"):
        normalize_filters(filters, variables)


def test_apply_filters_with_overflow_observation():
    """Test that out-of-range observation values raise the correct error code."""
    variables = _variables()
    normalized_filters = [
        {
            "variable": "measurement",
            "operator": "gte",
            "value": 100.0,
            "reason_code": "TEST_REASON",
        }
    ]
    rows = [
        {"measurement": 10**400},
    ]
    with pytest.raises(ValueError, match="ANALYSIS_ROW_FILTER_NON_NUMERIC_OBSERVATION"):
        apply_filters(rows, normalized_filters, variables)
