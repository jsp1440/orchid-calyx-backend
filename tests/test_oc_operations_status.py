from scripts.oc_operations_status import build_operations_status


def issue(number, *labels, **extra):
    return {"number": number, "labels": list(labels), **extra}


def test_operations_status_projects_canonical_health_and_exception_fields():
    snapshot = {
        "issues": [
            issue(10, "oc-queued"),
            issue(
                11,
                "oc-running",
                lease={"owner": "lane-1", "age_seconds": 42, "stale": False},
            ),
            issue(
                12,
                "oc-validating",
                validation_target={"pr": 88, "head_sha": "abc123"},
            ),
            issue(13, "oc-runtime-backoff"),
        ],
        "autonomous_prs": [
            {
                "number": 88,
                "head_sha": "abc123",
                "ci_state": "success",
                "mergeable": True,
            }
        ],
        "provider": {
            "status": "degraded",
            "degraded": True,
            "reason_code": "capacity",
        },
        "integration": {
            "ready": True,
            "target": "main",
            "head_sha": "def456",
            "ahead_by": 3,
        },
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
    assert status["validating_targets"] == [
        {"issue": 12, "pr": 88, "head_sha": "abc123"}
    ]
    assert status["autonomous_prs"][0]["ci_state"] == "success"
    assert status["provider"] == {
        "status": "degraded",
        "degraded": True,
        "reason_code": "capacity",
    }
    assert status["integration"]["ready"] is True
    assert status["violations"] == []
    assert status["exception_class"] == "none"
    assert status["owner_decision_required"] is False
    assert status["owner_exception_category"] is None
    assert status["should_interrupt_owner"] is False


def test_operations_status_surfaces_invariants_as_engineering_exceptions():
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
    assert status["exception_class"] == "engineering_exception"
    assert status["autonomous_repair_available"] is True
    assert status["owner_decision_required"] is False
    assert status["should_interrupt_owner"] is False


def test_operations_status_exposes_owner_exception_only_at_real_boundary():
    status = build_operations_status(
        {
            "provider": {"status": "disabled", "reason_code": "quota"},
            "exception_context": {
                "anomaly": "provider_disabled",
                "protected_boundary": "paid_provider_restoration",
            },
        }
    )

    assert status["exception_class"] == "owner_exception"
    assert status["owner_decision_required"] is True
    assert status["owner_exception_category"] == "spending_provider_restoration"
    assert status["autonomous_repair_available"] is False
    assert status["independent_authorized_work_available"] is False
    assert status["should_interrupt_owner"] is True


def test_operations_status_suppresses_owner_interrupt_when_safe_work_remains():
    status = build_operations_status(
        {
            "provider": {"status": "disabled", "reason_code": "quota"},
            "deterministic_work_available": True,
            "exception_context": {
                "anomaly": "provider_disabled",
                "protected_boundary": "paid_provider_restoration",
            },
        }
    )

    assert status["exception_class"] == "engineering_exception"
    assert status["owner_decision_required"] is False
    assert status["independent_authorized_work_available"] is True
    assert status["should_interrupt_owner"] is False


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
        "exception_context": {
            "anomaly": "lane_blocked",
            "detail": "internal vulnerability detail",
            "coordinates": [-1.0, 2.0],
        },
        "exceptions": [
            {
                "category": "sensitive_locality",
                "coordinates": [-1.0, 2.0],
                "detail": "must-not-leak",
            }
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
    assert "must-not-leak" not in rendered
    assert "coordinates" not in rendered
    assert "credentials" not in rendered
    assert status["exception_class"] == "engineering_exception"
    assert status["owner_exception_category"] is None
    assert status["should_interrupt_owner"] is False
