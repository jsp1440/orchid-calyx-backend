"""Test that score_priority correctly handles zero confidence.

Issue #1923: Explicit 0.0 confidence should be kept, not defaulted to 0.3.
Only missing or None confidence should default to 0.3.
"""
import pytest

from runtime.executive.scorer import score_priority


def test_confidence_zero_is_kept():
    """Test that confidence=0.0 is preserved and not defaulted to 0.3."""
    subsystem = {"id": "x", "completion": 50, "confidence": 0.0}
    result = score_priority(subsystem)

    # With confidence 0.0, evidence_confidence should be 0.0
    assert result["factors"]["evidence_confidence"] == pytest.approx(0.0)
    # build_readiness should be max(10, min(100, 50 + 0.0 * 20)) = max(10, 50) = 50
    assert result["factors"]["build_readiness"] == pytest.approx(50.0)
    # Score should be around 41.25
    assert result["score"] == pytest.approx(41.25, abs=0.1)


def test_confidence_missing_defaults_to_0_3():
    """Test that missing confidence defaults to 0.3."""
    subsystem = {"id": "x", "completion": 50}
    result = score_priority(subsystem)

    # With confidence defaulted to 0.3, evidence_confidence should be 30.0
    assert result["factors"]["evidence_confidence"] == pytest.approx(30.0)
    # build_readiness should be max(10, min(100, 50 + 0.3 * 20)) = max(10, 56) = 56
    assert result["factors"]["build_readiness"] == pytest.approx(56.0)
    # Score should be around 43.23
    assert result["score"] == pytest.approx(43.23, abs=0.1)


def test_confidence_none_defaults_to_0_3():
    """Test that None confidence defaults to 0.3."""
    subsystem = {"id": "x", "completion": 50, "confidence": None}
    result = score_priority(subsystem)

    # With confidence defaulted to 0.3, evidence_confidence should be 30.0
    assert result["factors"]["evidence_confidence"] == pytest.approx(30.0)
    # build_readiness should be max(10, min(100, 50 + 0.3 * 20)) = max(10, 56) = 56
    assert result["factors"]["build_readiness"] == pytest.approx(56.0)
    # Score should be around 43.23
    assert result["score"] == pytest.approx(43.23, abs=0.1)


def test_confidence_0_9_is_unchanged():
    """Test that confidence=0.9 works as before."""
    subsystem = {"id": "x", "completion": 50, "confidence": 0.9}
    result = score_priority(subsystem)

    # With confidence 0.9, evidence_confidence should be 90.0
    assert result["factors"]["evidence_confidence"] == pytest.approx(90.0)
    # build_readiness should be max(10, min(100, 50 + 0.9 * 20)) = max(10, 68) = 68
    assert result["factors"]["build_readiness"] == pytest.approx(68.0)
    # Score should be higher than the 0.0 case
    assert result["score"] > 41.0  # Should be higher than confidence 0.0 case (41.25)
