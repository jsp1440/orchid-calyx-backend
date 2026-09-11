from scripts.oc_control_plane_health import (
    UNKNOWN,
    build_contract_snapshot,
    build_health,
    classify_ci,
    evaluate_completion_pulse,
)


def test_runner_zero_with_no_steps_is_external_infrastructure_not_code_failure():
    result = classify_ci([{"id": 42, "status": "completed", "conclusion": "failure", "jobs": [
        {"conclusion": "failure", "runner_id": 0, "steps": []}
    ]}])
    assert result == {
        "state": "EXTERNAL_INFRASTRUCTURE_BLOCKED",
        "reason": "runner_allocation_failure",
        "run_id": 42,
        "runner_id": 0,
        "executed_step_count": 0,
    }


def test_executed_failure_is_kept_separate_from_infrastructure_failure():
    result = classify_ci([{"id": 43, "status": "completed", "conclusion": "failure", "jobs": [
        {"conclusion": "failure", "runner_id": 9, "steps": [{"conclusion": "failure"}]}
    ]}])
    assert result["state"] == "CODE_OR_CHECK_FAILURE"


def test_in_progress_run_is_unknown_not_fabricated_code_failure():
    # A queued/in-progress run has no failure evidence yet; classifying it as a
    # code failure would fabricate production status on every active pulse.
    for status in ("queued", "in_progress"):
        result = classify_ci([{"id": 45, "status": status, "conclusion": None, "jobs": []}])
        assert result["state"] == UNKNOWN
        assert result["run_id"] == 45


def test_unknown_values_are_not_fabricated_as_zero():
    health = build_health({"issues": []})
    assert health["stale_lease_count"] == UNKNOWN
    assert health["duplicate_authoritative_mission_count"] == UNKNOWN
    assert health["last_successful_exact_head_validation"] == UNKNOWN


def test_zero_running_reason_uses_runner_evidence():
    health = build_health({
        "issues": [{"number": 1193, "labels": ["oc-queued", "oc-p0"]}],
        "scheduler_runs": [{"id": 44, "status": "completed", "conclusion": "failure", "jobs": [
            {"conclusion": "failure", "runner_id": 0, "steps": []}
        ]}],
    })
    assert health["current_running_lease"] is None
    assert health["reason_no_work_running"] == "scheduler_job_never_received_a_runner"


def test_contract_snapshot_preserves_exact_head_provider_and_lease_evidence():
    pulse = {
        "generated_at": "2026-09-11T20:00:00Z",
        "issues": [
            {
                "number": 1264,
                "labels": ["oc-validating"],
                "validation_target": {"pr": 1357, "head_sha": "abc123"},
            }
        ],
        "leases": [],
        "dispatch_fingerprints": ["1264:abc123"],
        "provider_availability_state": "no_api",
        "integration_head": "integration-sha",
        "integration_ready": True,
        "deterministic_work_available": True,
    }

    snapshot = build_contract_snapshot(pulse)

    assert snapshot["schema"] == "oc.completion-health-snapshot.v1"
    assert snapshot["issues"][0]["validation_target"]["head_sha"] == "abc123"
    assert snapshot["provider"]["status"] == "no_api"
    assert snapshot["integration"] == {
        "head_sha": "integration-sha",
        "ready": True,
    }


def test_healthy_completion_pulse_is_checked_by_canonical_contract():
    checked = evaluate_completion_pulse(
        {
            "issues": [{"number": 1264, "labels": ["oc-queued"]}],
            "leases": [],
            "dispatch_fingerprints": ["1264:material-v1"],
            "provider": {"status": "no_api"},
            "deterministic_work_available": True,
        }
    )

    assert checked["report"]["healthy"] is True
    assert checked["report"]["counts"]["queued"] == 1
    assert checked["report"]["exception_decision"]["action"] == (
        "park_provider_and_continue_deterministic_work"
    )


def test_inconsistent_completion_pulse_fails_closed_with_repair_signal():
    checked = evaluate_completion_pulse(
        {
            "issues": [
                {
                    "number": 1264,
                    "labels": ["oc-running", "oc-runtime-backoff"],
                }
            ],
            "leases": [],
            "dispatch_fingerprints": ["1264:material-v1", "1264:material-v1"],
            "provider": {"status": "no_api"},
            "deterministic_work_available": True,
        }
    )

    report = checked["report"]
    assert report["healthy"] is False
    assert {
        "executable_parked_conflict",
        "running_lease_cardinality",
        "duplicate_dispatch_fingerprint",
    } <= {violation["type"] for violation in report["violations"]}
    assert report["exception_decision"]["exception_class"] == "engineering_exception"
    assert report["exception_decision"]["should_interrupt_owner"] is False


def test_legacy_health_receipt_embeds_contract_evidence():
    receipt = build_health(
        {
            "issues": [{"number": 1264, "labels": ["oc-queued"]}],
            "leases": [],
            "dispatch_fingerprints": [],
        }
    )

    assert receipt["contract_snapshot"]["issues"][0]["number"] == 1264
    assert receipt["contract_health"]["healthy"] is True
