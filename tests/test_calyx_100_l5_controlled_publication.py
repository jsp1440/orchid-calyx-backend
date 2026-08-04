from runtime.calyx_certification.controlled_publication import (
    evaluate_controlled_publication,
)


def _request():
    return {
        "ledger_artifact_id": "ledger:1",
        "ledger_version": 4,
        "review_hash": "sha256:review",
        "source_hash": "sha256:source",
        "assertion_identity": "assertion:1",
        "current_human_approval": True,
        "review_hash_valid": True,
        "source_hash_valid": True,
        "stable_assertion_identity": True,
        "delegates_to_build_088_gate": True,
        "direct_graph_sql": False,
    }


def test_valid_request_is_only_eligible_for_canonical_gate():
    result = evaluate_controlled_publication(_request())
    assert result["eligible_for_build_088_gate"] is True
    assert result["production_publication_authorized"] is False


def test_direct_sql_or_stale_approval_fails_closed():
    request = _request()
    request["current_human_approval"] = False
    request["direct_graph_sql"] = True
    result = evaluate_controlled_publication(request)
    assert result["eligible_for_build_088_gate"] is False
    assert "CURRENT_HUMAN_APPROVAL_REQUIRED" in result["blockers"]
    assert "DIRECT_GRAPH_SQL_FORBIDDEN" in result["blockers"]
