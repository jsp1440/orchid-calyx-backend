import math

import pytest

from app.calyx_conversation.routes import (
    AnalysisRequest,
    DatasetAnalysisRequest,
    run_analysis,
    run_dataset_analysis,
    safe_expression,
)
from app.calyx_conversation.store import ConversationStore


def test_safe_expression_supports_scientific_math_without_eval():
    assert safe_expression("sqrt(81) + 2**3") == 17.0
    assert math.isclose(safe_expression("pi"), math.pi)


def test_safe_expression_rejects_python_object_access():
    with pytest.raises(ValueError):
        safe_expression("(1).__class__")


def test_safe_expression_rejects_non_finite_result():
    with pytest.raises((ValueError, OverflowError)):
        safe_expression("exp(10000)")


def test_summary_analysis_includes_quartiles_and_standard_error():
    result = run_analysis(AnalysisRequest(operation="summary", values=[1, 2, 3, 4]))
    assert result["result"]["count"] == 4
    assert result["result"]["mean"] == 2.5
    assert result["result"]["median"] == 2.5
    assert result["result"]["q1"] == 1.75
    assert result["result"]["q3"] == 3.25
    assert result["result"]["standard_error"] > 0


def test_correlation_analysis():
    result = run_analysis(AnalysisRequest(operation="correlation", x=[1, 2, 3], y=[2, 4, 6]))
    assert math.isclose(result["result"], 1.0)


def test_covariance_analysis():
    result = run_analysis(AnalysisRequest(operation="covariance", x=[1, 2, 3], y=[2, 4, 6]))
    assert math.isclose(result["result"], 2.0)


def test_linear_regression_analysis():
    result = run_analysis(AnalysisRequest(operation="linear_regression", x=[1, 2, 3], y=[3, 5, 7]))
    assert math.isclose(result["result"]["slope"], 2.0)
    assert math.isclose(result["result"]["intercept"], 1.0)
    assert math.isclose(result["result"]["r_squared"], 1.0)
    assert math.isclose(result["result"]["residual_sum_squares"], 0.0)


def test_percent_change_analysis():
    result = run_analysis(AnalysisRequest(operation="percent_change", values=[100, 125]))
    assert result["result"] == 25.0


def test_percent_change_rejects_zero_baseline():
    with pytest.raises(ValueError):
        run_analysis(AnalysisRequest(operation="percent_change", values=[0, 1]))


def test_confidence_interval_mean():
    result = run_analysis(
        AnalysisRequest(operation="confidence_interval_mean", values=[10, 11, 12, 13, 14], confidence=0.95)
    )
    assert result["result"]["lower"] < 12 < result["result"]["upper"]
    assert result["result"]["method"] == "normal-approximation"


def test_moving_average():
    result = run_analysis(AnalysisRequest(operation="moving_average", values=[1, 2, 3, 4, 5], window=3))
    assert result["result"] == [2.0, 3.0, 4.0]


def test_dataset_describe_handles_missing_and_non_numeric_values():
    result = run_dataset_analysis(
        DatasetAnalysisRequest(
            operation="describe",
            columns={"temperature": [10, 12, None, 14], "taxon": ["a", "b", "c", "d"]},
        )
    )
    assert result["row_count"] == 4
    assert result["columns"]["temperature"]["numeric_count"] == 3
    assert result["columns"]["temperature"]["mean"] == 12.0
    assert result["columns"]["taxon"]["numeric_count"] == 0


def test_dataset_correlation_matrix():
    result = run_dataset_analysis(
        DatasetAnalysisRequest(
            operation="correlation_matrix",
            columns={"x": [1, 2, 3, 4], "y": [2, 4, 6, 8], "z": [4, 3, 2, 1]},
        )
    )
    assert math.isclose(result["matrix"]["x"]["y"], 1.0)
    assert math.isclose(result["matrix"]["x"]["z"], -1.0)


def test_dataset_rejects_mismatched_column_lengths():
    with pytest.raises(ValueError):
        run_dataset_analysis(DatasetAnalysisRequest(columns={"x": [1, 2], "y": [1]}))


def test_memory_conversation_store_persists_transcript_and_context():
    store = ConversationStore(dsn=None)
    cid = store.create_or_touch(None, title="Orchid question", context={"taxon": "Thelymitra"})
    first = store.append(cid, "operator", "What do we know?")
    second = store.append(cid, "calyx", "Evidence found.", {"evidence": {"count": 2}})

    conversation = store.get(cid)
    assert conversation is not None
    assert conversation["context"]["taxon"] == "Thelymitra"
    assert [message["role"] for message in conversation["messages"]] == ["operator", "calyx"]
    assert first["message_id"] != second["message_id"]
    assert store.recent(limit=1)[0]["message_count"] == 2
    assert "What do we know?" in store.history_text(cid)
