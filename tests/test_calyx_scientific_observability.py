import json
import re

import pytest

from app.calyx_conversation.observability import ScientificTrace


def test_trace_has_w3c_compatible_identifiers_and_content_free_governance():
    trace = ScientificTrace("calyx.query")
    with trace.span("retrieval", prompt="must not leak", retrieval_mode="HYBRID"):
        pass
    result = trace.finish({"results": []})
    assert re.fullmatch(r"[0-9a-f]{32}", result["trace_id"])
    assert re.fullmatch(r"[0-9a-f]{16}", result["root_span_id"])
    assert "prompt" not in json.dumps(result).casefold()
    assert result["governance"]["content_recorded"] is False
    assert result["governance"]["knowledge_graph_mutation"] is False


def test_scientific_evaluations_preserve_unknown_and_detect_incomplete_provenance():
    trace = ScientificTrace("calyx.query")
    result = trace.finish({"results": [{"object_id": "e-1", "object_type": "paper", "citation": {"source_type": "journal"}}]})
    evaluations = {item["name"]: item for item in result["scientific_evaluations"]}
    assert evaluations["retrieval_grounding"]["status"] == "pass"
    assert evaluations["provenance_completeness"]["status"] == "incomplete"
    assert evaluations["counterevidence_visibility"]["status"] == "unknown"
    assert evaluations["locality_protection"]["status"] == "unknown"
    assert result["provider"]["measurement_state"] == "unavailable"
    assert result["provider"]["input_tokens"] is None


def test_circular_self_evidence_requires_review():
    trace = ScientificTrace("calyx.query")
    result = trace.finish({"results": [{"object_type": "calyx_hypothesis", "citation": {"source_type": "internal", "locator": "ledger:1"}}]})
    evaluations = {item["name"]: item for item in result["scientific_evaluations"]}
    assert evaluations["circular_self_evidence_risk"]["status"] == "review_required"


def test_span_records_error_type_without_error_message():
    trace = ScientificTrace("calyx.query")
    with pytest.raises(ValueError, match="sensitive detail"):
        with trace.span("retrieval"):
            raise ValueError("sensitive detail")
    result = trace.finish()
    assert result["status"] == "error"
    assert result["spans"][0]["error_type"] == "ValueError"
    assert "sensitive detail" not in json.dumps(result)
