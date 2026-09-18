from runtime.calyx_closed_loop import run_closed_loop_cycle
from runtime.calyx_execution_feedback import ExecutionEvidencePacket
from runtime.calyx_queue_director import DevelopmentIntent


def intent(source_key="frontend-660", issue_number=660, **kw):
    base = {
        "source_key": source_key,
        "issue_number": issue_number,
        "title": "Bounded autonomous work",
        "repo": "orchid-continuum-frontend",
        "objective": "Prove governed closed-loop execution",
        "acceptance_criteria": ("exact-head evidence is required",),
        "priority": 2,
    }
    base.update(kw)
    return DevelopmentIntent(**base)


def evidence(source_key="frontend-660", issue_number=660, **kw):
    base = {
        "task_key": f"issue-{issue_number}:closed-loop",
        "source_key": source_key,
        "repo": "orchid-continuum-frontend",
        "issue_number": issue_number,
        "state": "completed",
        "exact_head_sha": "b" * 40,
        "pr_number": 1,
        "tests_passed": True,
        "ci_conclusion": "success",
        "evidence": {"exact_head_verified": True, "provider_api_called": False},
    }
    base.update(kw)
    return ExecutionEvidencePacket(**base)


def snapshot(issue=None):
    return {
        "issues": [] if issue is None else [issue],
        "leases": [],
        "dispatch_fingerprints": [],
        "autonomous_prs": [],
    }


def test_depletion_selects_one_safe_intent():
    result = run_closed_loop_cycle(
        intents=[intent()],
        snapshot=snapshot(),
        reserve_depth=1,
    )
    assert result["refill"]["status"] == "refill_planned"
    assert len(result["refill"]["proposals"]) == 1
    assert result["no_api_mode"] is True
    assert result["action_authorized"] is False


def test_verified_completion_retires_same_intent_without_recreation():
    result = run_closed_loop_cycle(
        intents=[intent()],
        snapshot=snapshot(),
        execution_evidence=[evidence()],
        reserve_depth=1,
    )
    assert result["completed_source_keys"] == ["frontend-660"]
    assert result["refill"]["proposals"] == []


def test_failed_verification_requests_revision_without_duplicate_refill():
    first = run_closed_loop_cycle(
        intents=[intent()],
        snapshot=snapshot(),
        reserve_depth=1,
    )
    proposal = first["refill"]["proposals"][0]
    persisted = snapshot(
        {
            "state": "queued",
            "material_fingerprint": proposal["material_fingerprint"],
            "semantic_key": proposal["semantic_key"],
        }
    )
    second = run_closed_loop_cycle(
        intents=[intent()],
        snapshot=persisted,
        execution_evidence=[evidence(ci_conclusion="failure")],
        reserve_depth=1,
    )
    assert len(second["revision_requests"]) == 1
    assert second["refill"]["proposals"] == []


def test_owner_gate_remains_parked_and_never_refills():
    result = run_closed_loop_cycle(
        intents=[intent(protected_boundaries=("main-merge",))],
        snapshot=snapshot(),
        execution_evidence=[
            evidence(state="owner_gated", owner_gate_reason="main_merge")
        ],
        reserve_depth=1,
    )
    assert len(result["owner_gated"]) == 1
    assert result["refill"]["proposals"] == []
    assert result["refill"]["calyx_parked"][0]["reason"] == "owner_gate"


def test_completion_causes_deterministic_successor_refill():
    result = run_closed_loop_cycle(
        intents=[
            intent(),
            intent(source_key="backend-700", issue_number=700, repo="orchid-calyx-backend"),
        ],
        snapshot=snapshot(),
        execution_evidence=[evidence()],
        reserve_depth=1,
    )
    assert result["completed_source_keys"] == ["frontend-660"]
    assert len(result["refill"]["proposals"]) == 1
    assert result["refill"]["proposals"][0]["source_ref"] == "#700"


def test_provider_call_fails_closed():
    result = run_closed_loop_cycle(
        intents=[intent()],
        snapshot=snapshot(),
        execution_evidence=[evidence(provider_api_called=True)],
        reserve_depth=1,
    )
    assert len(result["blocked"]) == 1
    assert result["blocked"][0]["reason"] == "paid_provider_call_detected"
    assert result["provider_launch_authorized"] is False
    assert result["no_api_mode"] is True
