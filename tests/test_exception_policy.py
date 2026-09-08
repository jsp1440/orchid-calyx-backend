from app.autonomy.exception_policy import classify_exception


def test_queue_backoff_is_engineering_exception_not_owner_interrupt():
    decision = classify_exception(
        "queue_backoff_contradiction", autonomous_repair_available=True
    )
    assert decision.exception_class == "engineering_exception"
    assert decision.action == "repair"
    assert decision.should_interrupt_owner is False


def test_ci_failure_repairs_without_owner_interrupt():
    decision = classify_exception(
        "exact_head_ci_failure", autonomous_repair_available=True
    )
    assert decision.owner_decision_required is False
    assert decision.should_interrupt_owner is False


def test_stale_lease_and_duplicate_fingerprint_do_not_interrupt():
    for anomaly in ("stale_lease", "duplicate_fingerprint"):
        decision = classify_exception(anomaly, autonomous_repair_available=True)
        assert decision.exception_class == "engineering_exception"
        assert decision.should_interrupt_owner is False


def test_provider_disabled_continues_deterministic_work():
    decision = classify_exception(
        "provider_disabled", deterministic_work_available=True
    )
    assert decision.independent_authorized_work_available is True
    assert decision.action == "park_provider_and_continue_deterministic_work"
    assert decision.should_interrupt_owner is False


def test_paid_provider_restoration_interrupts_only_when_actual_blocker():
    blocked = classify_exception(
        "provider_disabled", protected_boundary="paid_provider_restoration"
    )
    assert blocked.exception_class == "owner_exception"
    assert blocked.owner_exception_category == "spending_provider_restoration"
    assert blocked.should_interrupt_owner is True

    bypassed = classify_exception(
        "provider_disabled",
        protected_boundary="paid_provider_restoration",
        deterministic_work_available=True,
    )
    assert bypassed.exception_class == "engineering_exception"
    assert bypassed.owner_decision_required is False
    assert bypassed.should_interrupt_owner is False


def test_protected_boundaries_are_owner_exceptions_when_no_safe_path_remains():
    boundaries = {
        "scientific_activation": "scientific_activation",
        "sensitive_locality_disclosure": "sensitive_locality",
        "security_authority_change": "credential_security",
        "destructive_operation": "destructive_irreversible",
        "production_activation": "production_activation",
        "integration_main_promotion": "integration_main_promotion",
    }
    for boundary, category in boundaries.items():
        decision = classify_exception("blocked", protected_boundary=boundary)
        assert decision.exception_class == "owner_exception"
        assert decision.owner_exception_category == category
        assert decision.should_interrupt_owner is True


def test_blocked_lane_does_not_interrupt_when_other_authorized_work_exists():
    decision = classify_exception(
        "lane_blocked", independent_authorized_work_available=True
    )
    assert decision.action == "continue_other_authorized_work"
    assert decision.should_interrupt_owner is False


def test_healthy_progress_does_not_notify_owner():
    decision = classify_exception(None)
    assert decision.exception_class == "none"
    assert decision.should_interrupt_owner is False
