from scripts.oc_operations_status import build_operations_status


def issue(number, *labels, **extra):
    return {"number": number, "labels": list(labels), **extra}


def test_operations_status_contract_projects_canonical_health():
    snapshot = {
        "issues": [
            issue(10, "oc-queued"),
            issue(
                11,
                "oc-running",
                lease={"owner": "lane-1", "age_seconds": 42, "stale": False},
            ),
            issue(12, "oc-validating", validation_target={"pr": 88, "head_sha": "abc123"}),
            issue(13, "oc-runtime-backoff"),
        ],
        "autonomous_prs": [
            {"number": 88, "head_sha": "abc123", "ci_state": "success", "mergeable": True}
        ],
        "provider": {"status": "degraded", "degraded": True, "reason_code": "capacity"},
        "integration": {"ready": True, "target": "main", "head_sha": "def456", "ahead_by": 3},
    }

    status = build_operations_status(snapshot)

    assert status["schema_version"] == "oc.operations-status.v1"
    assert status["healthy"] is True
    assert status["counts"]["queued"] == 1
    assert status["counts"]["running"] == 1
    assert status["counts"]["validating"] == 1
    assert status["counts"]["runtime_backoff"] == 1
    assert status["issues"]["queued"] == [10]
    assert status["lanes"] == [
        {"issue": 11, "lane": "lane-1", "age_seconds": 42, "stale": False}
    ]
    assert status["validating_targets"] == [{"issue": 12, "pr": 88, "head_sha": "abc123"}]
    assert status["autonomous_prs"][0]["ci_state"] == "success"
    assert status["provider"] == {
        "status": "degraded",
        "degraded": True,
        "reason_code": "capacity",
    }
    assert status["integration"]["ready"] is True
    assert status["violations"] == []


def test_operations_status_surfaces_invariants_without_reimplementing_them():
    snapshot = {
        "issues": [
            issue(
                21,
                "oc-running",
                lease={"owner": "lane-a", "age_seconds": 999, "stale": True},
            ),
            issue(22, "oc-validating", validation_target={"pr": 99}),
        ],
        "dispatch_fingerprints": ["same", "same"],
    }

    status = build_operations_status(snapshot)
    violation_types = {item["type"] for item in status["violations"]}

    assert status["healthy"] is False
    assert "stale_lease" in violation_types
    assert "duplicate_dispatch_fingerprint" in violation_types
    assert "validating_without_exact_head" in violation_types


def test_operations_status_redacts_unapproved_fields_and_exception_details():
    snapshot = {
        "issues": [issue(31, "oc-queued")],
        "provider": {
            "status": "ok",
            "api_key": "secret-provider-key",
            "endpoint": "private-endpoint",
        },
        "integration": {
            "ready": False,
            "target": "main",
            "private_provenance": "do-not-expose",
        },
        "autonomous_prs": [
            {
                "number": 101,
                "head_sha": "head101",
                "ci_state": "pending",
                "mergeable": None,
                "token": "secret-token",
            }
        ],
        "exceptions": [
            {"category": "security", "detail": "internal vulnerability detail"},
            {"category": "sensitive_locality", "coordinates": [-1.0, 2.0]},
            {"category": "ordinary_engineering", "detail": "not an owner exception"},
        ],
        "sensitive_locality": {"lat": -1.0, "lon": 2.0},
        "credentials": {"token": "secret"},
    }

    status = build_operations_status(snapshot)
    rendered = repr(status)

    assert "secret-provider-key" not in rendered
    assert "private-endpoint" not in rendered
    assert "do-not-expose" not in rendered
    assert "secret-token" not in rendered
    assert "internal vulnerability detail" not in rendered
    assert "coordinates" not in rendered
    assert "credentials" not in rendered
    assert status["owner_exception_categories"] == ["security", "sensitive_locality"]
