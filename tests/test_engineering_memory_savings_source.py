"""Test suite for engineering memory savings source reporting (issue #1922).

Verifies that _savings() reports "source" as "measured" only when at least one
savings field is a number; otherwise "unavailable".
"""

from __future__ import annotations

from app.engineering_memory.evaluation import _savings


def test_savings_source_unavailable_when_telemetry_none():
    """_savings(None) returns source as unavailable."""
    result = _savings(None)
    assert result["source"] == "unavailable"
    assert result["input_tokens_saved"] == "unavailable"
    assert result["output_tokens_saved"] == "unavailable"
    assert result["turns_saved"] == "unavailable"


def test_savings_source_unavailable_when_telemetry_empty_dict():
    """_savings({}) returns source as unavailable."""
    result = _savings({})
    assert result["source"] == "unavailable"
    assert result["input_tokens_saved"] == "unavailable"
    assert result["output_tokens_saved"] == "unavailable"
    assert result["turns_saved"] == "unavailable"


def test_savings_source_unavailable_when_no_metric_paired():
    """_savings({"baseline": {"turns": 3}}) returns source as unavailable.

    Even though telemetry dict is provided, no metrics are actually paired
    (baseline has turns but enabled doesn't), so all savings fields are
    "unavailable" and source should also be "unavailable".
    """
    result = _savings({"baseline": {"turns": 3}})
    assert result["source"] == "unavailable"
    assert result["input_tokens_saved"] == "unavailable"
    assert result["output_tokens_saved"] == "unavailable"
    assert result["turns_saved"] == "unavailable"


def test_savings_source_measured_when_metric_paired():
    """_savings with paired metrics returns source as "measured".

    _savings({"baseline": {"turns": 3}, "enabled": {"turns": 2}})
    should return source "measured" with turns_saved = 1.
    """
    result = _savings({"baseline": {"turns": 3}, "enabled": {"turns": 2}})
    assert result["source"] == "measured"
    assert result["turns_saved"] == 1
    # Other metrics still unavailable since not provided
    assert result["input_tokens_saved"] == "unavailable"
    assert result["output_tokens_saved"] == "unavailable"


def test_savings_source_measured_with_multiple_metrics():
    """_savings returns "measured" when any metric is paired."""
    result = _savings({
        "baseline": {"input_tokens": 100, "output_tokens": 50, "turns": 5},
        "enabled": {"input_tokens": 80, "output_tokens": 40, "turns": 3},
    })
    assert result["source"] == "measured"
    assert result["input_tokens_saved"] == 20
    assert result["output_tokens_saved"] == 10
    assert result["turns_saved"] == 2


def test_savings_source_unavailable_when_only_baseline_has_metric():
    """_savings returns unavailable source when only one side has a metric."""
    result = _savings({"baseline": {"input_tokens": 100}})
    assert result["source"] == "unavailable"
    assert result["input_tokens_saved"] == "unavailable"


def test_savings_source_unavailable_when_only_enabled_has_metric():
    """_savings returns unavailable source when only enabled has a metric."""
    result = _savings({"enabled": {"turns": 5}})
    assert result["source"] == "unavailable"
    assert result["turns_saved"] == "unavailable"


def test_savings_with_partial_metrics_paired():
    """_savings returns "measured" when at least one metric is fully paired."""
    result = _savings({
        "baseline": {"input_tokens": 100, "output_tokens": 50},
        "enabled": {"input_tokens": 80},
    })
    # input_tokens is paired, so source should be "measured"
    assert result["source"] == "measured"
    assert result["input_tokens_saved"] == 20
    # output_tokens is not paired (missing on enabled)
    assert result["output_tokens_saved"] == "unavailable"
    # turns is not provided at all
    assert result["turns_saved"] == "unavailable"
