from scripts.oc_health_contract import evaluate


def issue(number, *labels, **extra):
    return {"number": number, "labels": list(labels), **extra}


def test_healthy_queued_issue_has_no_exception():
    report = evaluate({"issues": [issue(1, "oc-queued")]})
    assert report["healthy"] is True
    assert report["counts"]["queued"] == 1
    assert report["violations"] == []
    assert report["exception_decision"]["exception_class"] == "none"
    assert report["exception_decision"]["should_interrupt_owner"] is False


def test_queued_backoff_is_engineering_exception_with_auto_repair():
    report = evaluate(
        {
            "issues": [
                issue(
                    308,
                    "oc-queued",
                    "oc-runtime-backoff",
                    "oc-repair-backoff",
                )
            ]
        }
    )
    assert report["healthy"] is False
    assert any(
        violation["type"] == "executable_parked_conflict"
        and violation["issue"] == 308
        for violation in report["violations"]
    )
    decision = report["exception_decision"]
    assert decision["exception_class"] == "engineering_exception"
    assert decision["autonomous_repair_available"] is True
    assert decision["owner_decision_required"] is False
    assert decision["should_interrupt_owner"] is False


def test_multiple_executable_states_are_rejected_without_owner_escalation():
    report = evaluate({"issues": [issue(2, "oc-queued", "oc-running")]})
    assert report["healthy"] is False
    assert any(
        violation["type"] == "multiple_executable_states"
        for violation in report["violations"]
    )
    assert report["exception_decision"]["exception_class"] == "engineering_exception"
    assert report["exception_decision"]["should_interrupt_owner"] is False


def test_running_requires_exactly_one_active_lease():
    no_lease = evaluate({"issues": [issue(3, "oc-running")]})
    assert any(
        violation["type"] == "running_lease_cardinality"
        and violation["active_leases"] == 0
        for violation in no_lease["violations"]
    )

    two_leases = evaluate(
        {
            "issues": [issue(3, "oc-running")],
            "leases": [
                {"id": "a", "issue": 3, "active": True},
                {"id": "b", "issue": 3, "active": True},
            ],
        }
    )
    assert any(
        violation["type"] == "running_lease_cardinality"
        and violation["active_leases"] == 2
        for violation in two_leases["violations"]
    )


def test_single_running_lease_is_healthy():
    report = evaluate(
        {
            "issues": [issue(4, "oc-running")],
            "leases": [{"id": "lease-4", "issue": 4, "active": True}],
        }
    )
    assert report["healthy"] is True


def test_inline_running_lease_is_healthy():
    report = evaluate(
        {
            "issues": [
                issue(
                    8,
                    "oc-running",
                    lease={"id": "lease-8", "owner": "lane-8"},
                )
            ]
        }
    )
    assert report["healthy"] is True


def test_orphan_and_stale_leases_are_engineering_exceptions():
    report = evaluate(
        {
            "issues": [issue(5, "oc-queued")],
            "leases": [
                {"id": "old", "issue": 5, "active": True, "stale": True}
            ],
        }
    )
    kinds = {violation["type"] for violation in report["violations"]}
    assert "orphan_active_lease" in kinds
    assert "stale_lease" in kinds
    assert report["exception_decision"]["exception_class"] == "engineering_exception"
    assert report["exception_decision"]["should_interrupt_owner"] is False


def test_duplicate_dispatch_fingerprint_is_suppressed_without_owner_interrupt():
    report = evaluate(
        {"issues": [], "dispatch_fingerprints": ["301:abc", "301:abc"]}
    )
    assert report["healthy"] is False
    assert report["violations"] == [
        {"type": "duplicate_dispatch_fingerprint", "fingerprint": "301:abc"}
    ]
    assert report["exception_decision"]["exception_class"] == "engineering_exception"
    assert report["exception_decision"]["should_interrupt_owner"] is False


def test_validating_requires_exact_head():
    bad = evaluate({"issues": [issue(6, "oc-validating", pr=77)]})
    assert any(
        violation["type"] == "validating_without_exact_head"
        for violation in bad["violations"]
    )
    assert bad["exception_decision"]["exception_class"] == "engineering_exception"

    good = evaluate(
        {
            "issues": [
                issue(
                    6,
                    "oc-validating",
                    validation_target={"pr": 77, "head_sha": "deadbeef"},
                )
            ]
        }
    )
    assert good["healthy"] is True
    assert good["validating_targets"] == [
        {"issue": 6, "pr": 77, "head_sha": "deadbeef"}
    ]


def test_failed_exact_head_ci_is_engineering_exception_not_owner_exception():
    report = evaluate(
        {
            "autonomous_prs": [
                {"number": 88, "head_sha": "abc123", "ci_state": "failure"}
            ]
        }
    )
    assert any(
        violation["type"] == "exact_head_ci_failure"
        for violation in report["violations"]
    )
    decision = report["exception_decision"]
    assert decision["exception_class"] == "engineering_exception"
    assert decision["autonomous_repair_available"] is True
    assert decision["should_interrupt_owner"] is False


def test_provider_disabled_continues_deterministic_work():
    report = evaluate(
        {
            "provider": {"status": "disabled", "reason_code": "no_api"},
            "deterministic_work_available": True,
        }
    )
    decision = report["exception_decision"]
    assert decision["exception_class"] == "engineering_exception"
    assert decision["independent_authorized_work_available"] is True
    assert decision["should_interrupt_owner"] is False


def test_owner_exception_requires_actual_protected_boundary_and_no_safe_path():
    blocked = evaluate(
        {
            "provider": {"status": "disabled"},
            "exception_context": {
                "anomaly": "provider_disabled",
                "protected_boundary": "paid_provider_restoration",
            },
        }
    )
    decision = blocked["exception_decision"]
    assert decision["exception_class"] == "owner_exception"
    assert decision["owner_decision_required"] is True
    assert decision["owner_exception_category"] == "spending_provider_restoration"
    assert decision["should_interrupt_owner"] is True

    bypassed = evaluate(
        {
            "provider": {"status": "disabled"},
            "deterministic_work_available": True,
            "exception_context": {
                "anomaly": "provider_disabled",
                "protected_boundary": "paid_provider_restoration",
            },
        }
    )
    decision = bypassed["exception_decision"]
    assert decision["exception_class"] == "engineering_exception"
    assert decision["owner_decision_required"] is False
    assert decision["should_interrupt_owner"] is False


def test_blocked_lane_with_independent_work_does_not_interrupt_owner():
    report = evaluate(
        {
            "issues": [issue(44, "oc-blocked")],
            "exception_context": {"anomaly": "lane_blocked"},
            "independent_authorized_work_available": True,
        }
    )
    decision = report["exception_decision"]
    assert decision["exception_class"] == "engineering_exception"
    assert decision["independent_authorized_work_available"] is True
    assert decision["should_interrupt_owner"] is False
