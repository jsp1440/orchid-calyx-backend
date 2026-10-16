from __future__ import annotations

import pytest

from runtime.scientific_uncertainty import (
    mean_confidence_interval,
    mean_confidence_interval_from_summary,
)


def test_mean_confidence_interval_with_overflow_value():
    """Test that OverflowError is caught and mapped to UNCERTAINTY_MEAN_CI_VALUE_INVALID."""
    with pytest.raises(ValueError, match="UNCERTAINTY_MEAN_CI_VALUE_INVALID"):
        mean_confidence_interval([1, 2, 10**400], 0.95)


def test_mean_confidence_interval_from_summary_with_overflow_mean():
    """Test that OverflowError in mean is caught and mapped to UNCERTAINTY_MEAN_CI_MEAN_INVALID."""
    with pytest.raises(ValueError, match="UNCERTAINTY_MEAN_CI_MEAN_INVALID"):
        mean_confidence_interval_from_summary(
            sample_size=3, sample_mean=10**400, sample_sd=1.0, confidence_level=0.95
        )
