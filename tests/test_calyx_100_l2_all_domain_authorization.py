from runtime.knowledge_graph.all_domain_authorization import (
    evaluate_all_domain_authorization,
)


def test_all_domain_report_requires_zero_delta_and_integrity():
    report = {
        "domains": [
            {
                "domain": "taxonomy",
                "state": "completed",
                "second_pass_nodes": 0,
                "second_pass_edges": 0,
                "orphan_endpoints": 0,
                "duplicate_identities": 0,
                "integrity_ok": True,
            },
            {"domain": "climate", "state": "withheld", "reason": "policy hold"},
            {"domain": "mycorrhiza", "state": "unavailable", "reason": "source absent"},
        ]
    }
    result = evaluate_all_domain_authorization(report)
    assert result["ready_for_owner_authorization"] is True
    assert result["authorized"] is False
    assert result["production_graph_mutation"] is False


def test_all_domain_report_fails_closed_on_delta_or_missing_reason():
    report = {
        "domains": [
            {
                "domain": "media",
                "state": "completed",
                "second_pass_nodes": 1,
                "second_pass_edges": 0,
                "orphan_endpoints": 0,
                "duplicate_identities": 0,
                "integrity_ok": True,
            },
            {"domain": "molecular", "state": "unavailable"},
        ]
    }
    result = evaluate_all_domain_authorization(report)
    assert result["ready_for_owner_authorization"] is False
    assert "media:SECOND_PASS_NODE_DELTA" in result["blockers"]
    assert "molecular:UNAVAILABLE_REASON_MISSING" in result["blockers"]
