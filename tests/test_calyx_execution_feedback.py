from runtime.calyx_execution_feedback import (
    ExecutionEvidencePacket,
    classify_execution_evidence,
)


def packet(**kw):
    base = {
        "task_key": "issue-660:mounted-proof",
        "source_key": "frontend-660",
        "repo": "orchid-continuum-frontend",
        "issue_number": 660,
        "state": "completed",
        "exact_head_sha": "a" * 40,
        "pr_number": 658,
        "tests_passed": True,
        "ci_conclusion": "success",
        "evidence": {"tests": 2311, "chromium": "passed"},
    }
    base.update(kw)
    return ExecutionEvidencePacket(**base)


def test_verified_completion_returns_complete_without_action_authority():
    result = classify_execution_evidence(packet())
    assert result["disposition"] == "COMPLETE"
    assert result["reason"] == "verified_execution_complete"
    assert result["action_authorized"] is False
    assert result["provider_launch_authorized"] is False
    assert result["no_api_mode"] is True
    assert result["authority"] == "queue-bridge"


def test_failed_ci_returns_revise():
    result = classify_execution_evidence(packet(ci_conclusion="failure"))
    assert result["disposition"] == "REVISE"
    assert result["reason"] == "verification_failed"


def test_incomplete_completion_evidence_returns_revise():
    result = classify_execution_evidence(packet(exact_head_sha=None))
    assert result["disposition"] == "REVISE"
    assert result["reason"] == "completion_evidence_incomplete"


def test_blocked_and_backoff_remain_blocked():
    for state in ("blocked", "repair_backoff"):
        result = classify_execution_evidence(
            packet(state=state, blocked_reason="deterministic_failure")
        )
        assert result["disposition"] == "BLOCKED"
        assert result["reason"] == "deterministic_failure"


def test_owner_gate_is_never_downgraded():
    result = classify_execution_evidence(
        packet(state="owner_gated", owner_gate_reason="main_merge")
    )
    assert result["disposition"] == "OWNER_GATED"
    assert result["reason"] == "main_merge"
    assert result["action_authorized"] is False


def test_paid_provider_evidence_fails_closed():
    result = classify_execution_evidence(packet(provider_api_called=True))
    assert result["disposition"] == "BLOCKED"
    assert result["reason"] == "paid_provider_call_detected"
    assert result["provider_launch_authorized"] is False


def test_unchanged_evidence_has_stable_fingerprint():
    first = classify_execution_evidence(packet())["fingerprint"]
    second = classify_execution_evidence(packet())["fingerprint"]
    assert first == second
