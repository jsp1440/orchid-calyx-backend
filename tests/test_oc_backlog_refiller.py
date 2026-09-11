from scripts.oc_backlog_refiller import plan_refill


def issue(number, *labels, **extra):
    return {"number": number, "labels": list(labels), **extra}


def snapshot(*issues, leases=None, fingerprints=None, **extra):
    return {
        "issues": list(issues),
        "leases": list(leases or []),
        "dispatch_fingerprints": list(fingerprints or []),
        **extra,
    }


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
    state = snapshot(issue(1, "oc-queued"))
    result = plan_refill(
        state,
        [
            candidate("#2", "fp-2"),
            candidate("#3", "fp-3"),
            candidate("#4", "fp-4"),
        ],
        reserve_depth=3,
    )
    assert result["status"] == "refill_planned"
    assert result["deficit"] == 2
    assert [proposal["source_ref"] for proposal in result["proposals"]] == [
        "#2",
        "#3",
    ]


def test_duplicate_fingerprint_and_semantic_duplicate_are_suppressed():
    state = snapshot(
        issue(
            10,
            "oc-running",
            material_fingerprint="same",
            semantic_key="health-monitor",
        ),
        leases=[
            {
                "issue": 10,
                "id": "lease-10",
                "owner": "test-worker",
                "material_fingerprint": "same",
                "active": True,
            }
        ],
    )
    result = plan_refill(
        state,
        [
            candidate("#11", "same", semantic_key="other"),
            candidate("#12", "new", semantic_key="health-monitor"),
        ],
        reserve_depth=1,
    )
    assert result["status"] == "queue_empty_healthy"
    assert {item["reason"] for item in result["rejections"]} == {
        "duplicate_fingerprint",
        "semantic_duplicate",
    }


def test_dependency_gating_requires_completed_dependency():
    blocked = candidate("#20", "fp-20", dependencies=["contract-v1"])
    first = plan_refill(snapshot(), [blocked], reserve_depth=1)
    assert first["status"] == "queue_empty_healthy"
    assert first["rejections"] == [
        {"source_ref": "#20", "reason": "dependency_blocked"}
    ]

    second = plan_refill(
        snapshot(completed_dependencies=["contract-v1"]),
        [blocked],
        reserve_depth=1,
    )
    assert second["status"] == "refill_planned"
    assert second["proposals"][0]["dependencies"] == ["contract-v1"]


def test_protected_boundary_exhaustion_parks_truthfully():
    result = plan_refill(
        snapshot(),
        [candidate("#30", "fp-30", protected_boundaries=["production"])],
        reserve_depth=2,
    )
    assert result["status"] == "queue_empty_healthy"
    assert result["proposals"] == []
    assert result["rejections"] == [
        {"source_ref": "#30", "reason": "protected_boundary"}
    ]


def test_planner_failure_is_distinct_from_healthy_empty_queue():
    result = plan_refill(
        snapshot(),
        [],
        reserve_depth=1,
        planner_ok=False,
    )
    assert result["status"] == "queue_empty_planner_failed"
    assert result["rejections"] == [{"reason": "planner_unavailable"}]


def test_unhealthy_health_snapshot_fails_closed_without_proposals():
    result = plan_refill(
        snapshot(issue(40, "oc-queued", "oc-blocked")),
        [candidate("#41", "fp-41")],
        reserve_depth=2,
    )
    assert result["status"] == "planner_failed"
    assert result["proposals"] == []
    assert result["rejections"][0]["reason"] == "health_contract_violation"


def test_unauthorized_source_cannot_enter_reserve():
    result = plan_refill(
        snapshot(),
        [candidate("invented", "fp-x", source_kind="freeform")],
        reserve_depth=1,
    )
    assert result["status"] == "queue_empty_healthy"
    assert result["rejections"] == [
        {"source_ref": "invented", "reason": "unauthorized_source"}
    ]


def test_repeated_cycle_does_not_duplicate_unchanged_work():
    work = candidate("#50", "fp-50", semantic_key="durable-gap-50")
    first = plan_refill(snapshot(), [work], reserve_depth=1)
    assert first["status"] == "refill_planned"
    assert len(first["proposals"]) == 1

    proposed = first["proposals"][0]
    second_state = snapshot(
        issue(
            50,
            "oc-queued",
            material_fingerprint=proposed["material_fingerprint"],
            semantic_key=proposed["semantic_key"],
        ),
        fingerprints=[proposed["material_fingerprint"]],
    )
    second = plan_refill(second_state, [work], reserve_depth=1)
    assert second["status"] == "reserve_satisfied"
    assert second["proposals"] == []


def test_depleted_queue_refill_order_is_deterministic():
    candidates = [
        candidate("#later", "fp-later", priority=2, created_at="2026-09-01"),
        candidate("#b", "fp-b", priority=1, created_at="2026-09-02"),
        candidate("#a", "fp-a", priority=1, created_at="2026-09-02"),
    ]
    first = plan_refill(snapshot(), candidates, reserve_depth=2)
    second = plan_refill(snapshot(), list(reversed(candidates)), reserve_depth=2)

    assert first["proposals"] == second["proposals"]
    assert [item["source_ref"] for item in first["proposals"]] == ["#a", "#b"]
