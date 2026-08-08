import math

import pytest

from app.calyx_conversation.routes import AnalysisRequest, run_analysis, safe_expression


def test_safe_expression_supports_scientific_math_without_eval():
    assert safe_expression("sqrt(81) + 2**3") == 17.0
    assert math.isclose(safe_expression("pi"), math.pi)


def test_safe_expression_rejects_python_object_access():
    with pytest.raises(ValueError):
        safe_expression("(1).__class__")


def test_summary_analysis():
    result = run_analysis(AnalysisRequest(operation="summary", values=[1, 2, 3, 4]))
    assert result["result"]["count"] == 4
    assert result["result"]["mean"] == 2.5
    assert result["result"]["median"] == 2.5


def test_correlation_analysis():
    result = run_analysis(AnalysisRequest(operation="correlation", x=[1, 2, 3], y=[2, 4, 6]))
    assert math.isclose(result["result"], 1.0)


def test_linear_regression_analysis():
    result = run_analysis(AnalysisRequest(operation="linear_regression", x=[1, 2, 3], y=[3, 5, 7]))
    assert math.isclose(result["result"]["slope"], 2.0)
    assert math.isclose(result["result"]["intercept"], 1.0)
    assert math.isclose(result["result"]["r_squared"], 1.0)


def test_percent_change_analysis():
    result = run_analysis(AnalysisRequest(operation="percent_change", values=[100, 125]))
    assert result["result"] == 25.0


def test_percent_change_rejects_zero_baseline():
    with pytest.raises(ValueError):
        run_analysis(AnalysisRequest(operation="percent_change", values=[0, 1]))
