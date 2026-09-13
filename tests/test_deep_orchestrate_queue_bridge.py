from app.calyx_orchestrator.deep_orchestrate import (
    AUTH_PRODUCTION,
    AUTH_WORKSPACE,
    DeepOrchestrate,
    Priority,
    TaskLeaf,
    TaskState,
)
from runtime.deep_orchestrate_queue_bridge import plan_deep_orchestrate_refill


def leaf(
    key,
    issue_number,
    *,
    priority=Priority.P1,
    authority_class=AUTH_WORKSPACE,
    consequence_risk="low",
    dependencies=None,
):
    return TaskLeaf(
        key=key,
        title=f"Implement {key}",
        repo="orchid-calyx-backend",
        module="app/calyx_orchestrator",
        priority=priority,
        authority_class=authority_class,
        consequence_risk=consequence_risk,
        issue_number=issue_number,
        dependencies=list(dependencies or []),
        acceptance_criteria=["focused tests pass"],
    )


def snapshot(*issues, **extra):
    return {
        "issues": list(issues),
        "leases": [],
        "dispatch_fingerprints": [],
        **extra,
    }


def test_depleted_reserve_admits_only_ready_issue_backed_leaves():
    orchestrator = DeepOrchestrate(configured_width=2)
    orchestrator.register(leaf("event-continuation", 1023, priority=Priority.P0))
    orchestrator.register(leaf("unmaterialized-idea", None, priority=Priority.P0))

    result = plan_deep_orchestrate_refill(
        orchestrator,
        snapshot(),
        reserve_depth=2,
    )

    assert result["status"] == "refill_planned"
    assert [item["source_ref"] for item in result["proposals"]] == ["#1023"]
    assert result["proposals"][0]["queue_source_kind"] == "autonomous-orchestrator"
    assert result["source_rejections"] == [
        {"task_key": "unmaterialized-idea", "reason": "missing_issue_lineage"}
    ]
    assert result["provider_launch_authorized"] is False
    assert result["no_api_mode"] is True


def test_repeated_cycle_suppresses_unchanged_semantic_lineage():
    orchestrator = DeepOrchestrate()
    orchestrator.register(leaf("event-continuation", 1023))
    first = plan_deep_orchestrate_refill(
        orchestrator,
        snapshot(),
        reserve_depth=1,
    )
    proposal = first["proposals"][0]

    repeated = plan_deep_orchestrate_refill(
        orchestrator,
        snapshot(
            {
                "number": 1023,
                "labels": ["oc-queued"],
                "material_fingerprint": proposal["material_fingerprint"],
                "semantic_key": proposal["semantic_key"],
            }
        ),
        reserve_depth=2,
    )

    assert repeated["proposals"] == []
    assert repeated["status"] == "reserve_below_target_no_eligible_candidates"
    assert {item["reason"] for item in repeated["rejections"]} == {
        "duplicate_fingerprint"
    }


def test_completed_blocked_and_owner_gated_leaves_never_enter_reserve():
    orchestrator = DeepOrchestrate()
    completed = leaf("completed", 10)
    completed.state = TaskState.COMPLETED
    blocked = leaf("blocked", 11)
    blocked.state = TaskState.BLOCKED
    protected = leaf(
        "production",
        12,
        authority_class=AUTH_PRODUCTION,
    )
    orchestrator.register_many([completed, blocked, protected])

    result = plan_deep_orchestrate_refill(
        orchestrator,
        snapshot(),
        reserve_depth=3,
    )

    assert result["proposals"] == []
    assert result["status"] == "queue_empty_healthy"
    assert result["source_state_counts"] == {
        "blocked": 1,
        "completed": 1,
        "owner_gated": 1,
    }


def test_high_risk_leaf_fails_closed_even_if_marked_workspace_authority():
    orchestrator = DeepOrchestrate()
    orchestrator.register(
        leaf("high-risk", 20, consequence_risk="high")
    )

    result = plan_deep_orchestrate_refill(
        orchestrator,
        snapshot(),
        reserve_depth=1,
    )

    assert result["proposals"] == []
    assert result["rejections"] == [
        {"source_ref": "#20", "reason": "protected_boundary"}
    ]


def test_dependency_gate_and_refill_order_are_deterministic():
    orchestrator = DeepOrchestrate()
    dependency = leaf("dependency", 30)
    dependency.state = TaskState.COMPLETED
    orchestrator.register_many(
        [
            dependency,
            leaf(
                "later",
                32,
                priority=Priority.P2,
                dependencies=["dependency"],
            ),
            leaf(
                "first",
                31,
                priority=Priority.P0,
                dependencies=["dependency"],
            ),
        ]
    )

    first = plan_deep_orchestrate_refill(
        orchestrator,
        snapshot(completed_dependencies=["dependency"]),
        reserve_depth=2,
    )
    second = plan_deep_orchestrate_refill(
        orchestrator,
        snapshot(completed_dependencies=["dependency"]),
        reserve_depth=2,
    )

    assert first["proposals"] == second["proposals"]
    assert [item["source_ref"] for item in first["proposals"]] == ["#31", "#32"]
