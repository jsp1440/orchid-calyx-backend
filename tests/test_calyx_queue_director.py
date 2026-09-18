from runtime.calyx_queue_director import (
    DevelopmentIntent,
    normalize_intents,
    plan_calyx_refill,
)


def intent(**kw):
    base = {
        "source_key": "frontend-660",
        "issue_number": 660,
        "title": "Research Station to Matrix",
        "repo": "orchid-continuum-frontend",
        "objective": "Preserve canonical project identity",
        "acceptance_criteria": ("mounted journey proves exact project return",),
        "priority": 5,
    }
    base.update(kw)
    return DevelopmentIntent(**base)


def snapshot(**kw):
    base = {
        "issues": [],
        "leases": [],
        "dispatch_fingerprints": [],
        "autonomous_prs": [],
    }
    base.update(kw)
    return base


def test_safe_intent_becomes_bounded_candidate():
    result = normalize_intents([intent()])
    assert result["no_api_mode"] is True
    assert result["provider_launch_authorized"] is False
    assert result["authority"] == "queue-bridge"
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["source_ref"] == "#660"
    assert result["candidates"][0]["queue_source_kind"] == "autonomous-orchestrator"


def test_duplicate_source_is_suppressed():
    result = normalize_intents([intent(), intent()])
    assert len(result["candidates"]) == 1
    assert result["rejected"] == [
        {"source_key": "frontend-660", "reason": "duplicate_source_key"}
    ]


def test_provider_work_parks_under_no_api():
    result = normalize_intents([intent(requires_provider=True)])
    assert result["candidates"] == []
    assert result["parked"][0]["reason"] == "runtime_backoff_no_api"


def test_protected_work_is_owner_gated():
    result = normalize_intents([intent(protected_boundaries=("main-merge",))])
    assert result["candidates"] == []
    assert result["parked"][0]["reason"] == "owner_gate"


def test_unbounded_or_unknown_repo_fails_closed():
    result = normalize_intents(
        [intent(repo="unknown"), intent(source_key="empty", acceptance_criteria=())]
    )
    assert result["candidates"] == []
    assert len(result["rejected"]) == 2


def test_fingerprint_is_stable_for_unchanged_reasoning():
    first = normalize_intents([intent()])["candidates"][0]["material_fingerprint"]
    second = normalize_intents([intent()])["candidates"][0]["material_fingerprint"]
    assert first == second


def test_calyx_intent_enters_canonical_refill_once():
    first = plan_calyx_refill([intent()], snapshot(), reserve_depth=1)
    assert first["status"] == "refill_planned"
    assert len(first["proposals"]) == 1
    proposal = first["proposals"][0]
    assert proposal["source_ref"] == "#660"
    assert proposal["queue_source_kind"] == "autonomous-orchestrator"
    assert first["no_api_mode"] is True

    persisted = snapshot(
        issues=[
            {
                "state": "queued",
                "material_fingerprint": proposal["material_fingerprint"],
                "semantic_key": proposal["semantic_key"],
            }
        ]
    )
    second = plan_calyx_refill([intent()], persisted, reserve_depth=2)
    assert second["proposals"] == []
    reasons = {item["reason"] for item in second["rejections"]}
    assert reasons & {"duplicate_fingerprint", "semantic_duplicate"}


def test_planner_failure_does_not_authorize_provider():
    result = plan_calyx_refill([intent()], snapshot(), reserve_depth=1, planner_ok=False)
    assert result["status"] == "queue_empty_planner_failed"
    assert result["provider_launch_authorized"] is False
    assert result["no_api_mode"] is True


def test_unknown_protected_boundary_fails_closed_to_owner_gate():
    result = normalize_intents(
        [intent(protected_boundaries=("future-sensitive-boundary",))]
    )
    assert result["candidates"] == []
    assert result["parked"][0]["reason"] == "owner_gate"
    assert result["parked"][0]["unknown_boundaries"] == ["future-sensitive-boundary"]
