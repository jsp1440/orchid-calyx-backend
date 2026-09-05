from scripts.oc_backlog_refiller import plan_refill


def issue(number, *labels, **extra):
    return {"number": number, "labels": list(labels), **extra}


def candidate(ref, fingerprint, **extra):
    return {
        "source_kind": "issue",
        "source_ref": ref,
        "title": f"Work {ref}",
        "material_fingerprint": fingerprint,
        "priority": 1,
        **extra,
    }


def test_refills_only_to_configured_reserve_depth():
    snapshot = {"issues": [issue(1, "oc-queued")]}
    result = plan_refill(
        snapshot,
        [candidate("#2", "fp-2"), candidate("#3", "fp-3"), candidate("#4", "fp-4")],
        reserve_depth=3,
    )
    assert result["status"] == "refill_planned"
    assert result["deficit"] == 2
    assert [p["source_ref"] for p in result["proposals"]] == ["#2", "#3"]


def test_duplicate_fingerprint_and_semantic_duplicate_are_suppressed():
    snapshot = {
        "issues": [issue(10, "oc-running", material_fingerprint="same", semantic_key="health-monitor")],
        "leases": [{"issue": 10, "id": "lease-10", "active": True}],
    }
    result = plan_refill(
        snapshot,
        [
            candidate("#11", "same", semantic_key="other"),
            candidate("#12", "new", semantic_key="health-monitor"),
        ],
        reserve_depth=1,
    )
    assert result["status"] == "queue_empty_healthy"
    assert {item["reason"] for item in result["rejections"]} == {"duplicate_fingerprint", "semantic_duplicate"}


def test_dependency_gating_requires_completed_dependency():
    blocked = candidate("#20", "fp-20", dependencies=["contract-v1"])
    first = plan_refill({"issues": []}, [blocked], reserve_depth=1)
    assert first["status"] == "queue_empty_healthy"
    assert first["rejections"] == [{"source_ref": "#20", "reason": "dependency_blocked"}]

    second = plan_refill(
        {"issues": [], "completed_dependencies": ["contract-v1"]},
        [blocked],
        reserve_depth=1,
    )
    assert second["status"] == "refill_planned"
    assert second["proposals"][0]["dependencies"] == ["contract-v1"]


def test_protected_boundary_exhaustion_parks_truthfully():
    result = plan_refill(
        {"issues": []},
        [candidate("#30", "fp-30", protected_boundaries=["production"])],
        reserve_depth=2,
    )
    assert result["status"] == "queue_empty_healthy"
    assert result["proposals"] == []
    assert result["rejections"] == [{"source_ref": "#30", "reason": "protected_boundary"}]


def test_planner_failure_is_distinct_from_healthy_empty_queue():
    result = plan_refill({"issues": []}, [], reserve_depth=1, planner_ok=False)
    assert result["status"] == "queue_empty_planner_failed"
    assert result["rejections"] == [{"reason": "planner_unavailable"}]


def test_unhealthy_health_snapshot_fails_closed_without_proposals():
    result = plan_refill(
        {"issues": [issue(40, "oc-queued", "oc-blocked")]},
        [candidate("#41", "fp-41")],
        reserve_depth=2,
    )
    assert result["status"] == "planner_failed"
    assert result["proposals"] == []
    assert result["rejections"][0]["reason"] == "health_contract_violation"


def test_unauthorized_source_cannot_enter_reserve():
    result = plan_refill(
        {"issues": []},
        [candidate("invented", "fp-x", source_kind="freeform")],
        reserve_depth=1,
    )
    assert result["status"] == "queue_empty_healthy"
    assert result["rejections"] == [{"source_ref": "invented", "reason": "unauthorized_source"}]
