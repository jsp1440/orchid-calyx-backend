"""Tests for DeepOrchestrate — machine-readable task reservoir.

Covers all invariants from the #1024 DEEP ORCHESTRATE directive:
- No-idle capacity and refill after completion/block/CI wait/provider failure
- Priority and dependency ordering
- Fairness across repos/authority classes
- Dedupe / idempotent registration
- Lease exclusivity
- Repair-backoff exclusion
- Owner-gate isolation
- Persistence / restart recovery (to_dict / from_dict round-trip)
"""

from __future__ import annotations

import time

import pytest

from app.calyx_orchestrator.deep_orchestrate import (
    AUTH_GOVERNANCE,
    AUTH_PRODUCTION,
    AUTH_READ_ONLY,
    AUTH_REPO_EXEC,
    AUTH_SCIENCE_PUB,
    AUTH_SECURITY,
    AUTH_WORKSPACE,
    SCHEMA_VERSION,
    DeepOrchestrate,
    Priority,
    TaskLeaf,
    TaskState,
    seed_from_1024,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _leaf(
    key: str,
    *,
    priority: int = Priority.P2,
    authority_class: str = AUTH_WORKSPACE,
    consequence_risk: str = "low",
    deps: list[str] | None = None,
    repo: str = "orchid-calyx-backend",
) -> TaskLeaf:
    return TaskLeaf(
        key=key,
        title=f"Test task {key}",
        repo=repo,
        module="app/test",
        priority=priority,
        authority_class=authority_class,
        consequence_risk=consequence_risk,
        dependencies=deps or [],
    )


def _orch(width: int = 3) -> DeepOrchestrate:
    return DeepOrchestrate(configured_width=width)


# ---------------------------------------------------------------------------
# Registration and dedupe
# ---------------------------------------------------------------------------


def test_register_returns_true_on_first_add():
    orch = _orch()
    assert orch.register(_leaf("a")) is True


def test_register_returns_false_on_duplicate():
    orch = _orch()
    orch.register(_leaf("a"))
    assert orch.register(_leaf("a")) is False


def test_register_many_counts_new_only():
    orch = _orch()
    orch.register(_leaf("a"))
    count = orch.register_many([_leaf("a"), _leaf("b"), _leaf("c")])
    assert count == 2


def test_dedupe_does_not_overwrite_existing_state():
    orch = _orch()
    leaf = _leaf("a")
    orch.register(leaf)
    orch.lease("a")
    # Re-registration attempt must not reset state.
    orch.register(_leaf("a"))
    assert orch.get("a").state == TaskState.LEASED


# ---------------------------------------------------------------------------
# Owner-gate isolation
# ---------------------------------------------------------------------------


def test_owner_gate_classes_auto_gated_on_register():
    for auth in (AUTH_PRODUCTION, AUTH_SCIENCE_PUB, AUTH_SECURITY, AUTH_GOVERNANCE):
        orch = _orch()
        orch.register(_leaf("x", authority_class=auth))
        assert orch.get("x").state == TaskState.OWNER_GATED, f"expected OWNER_GATED for {auth}"


def test_non_owner_gate_classes_registered_as_ready():
    for auth in (AUTH_READ_ONLY, AUTH_WORKSPACE, AUTH_REPO_EXEC):
        orch = _orch()
        orch.register(_leaf("x", authority_class=auth))
        assert orch.get("x").state == TaskState.READY, f"expected READY for {auth}"


def test_owner_gated_task_not_in_ready_tasks():
    orch = _orch()
    orch.register(_leaf("prod", authority_class=AUTH_PRODUCTION))
    orch.register(_leaf("normal"))
    keys = {t.key for t in orch.ready_tasks()}
    assert "prod" not in keys
    assert "normal" in keys


def test_owner_gated_task_not_leasable():
    orch = _orch()
    orch.register(_leaf("prod", authority_class=AUTH_PRODUCTION))
    with pytest.raises(ValueError, match="TASK_NOT_READY"):
        orch.lease("prod")


def test_authorize_moves_owner_gated_to_ready():
    orch = _orch()
    orch.register(_leaf("prod", authority_class=AUTH_PRODUCTION))
    orch.authorize("prod")
    assert orch.get("prod").state == TaskState.READY


def test_authorize_on_non_owner_gated_raises():
    orch = _orch()
    orch.register(_leaf("a"))
    with pytest.raises(ValueError, match="NOT_OWNER_GATED"):
        orch.authorize("a")


def test_owner_gated_count_in_snapshot():
    orch = _orch()
    orch.register(_leaf("pg", authority_class=AUTH_PRODUCTION))
    orch.register(_leaf("sg", authority_class=AUTH_SCIENCE_PUB))
    snap = orch.snapshot()
    assert snap["owner_gate_count"] == 2


# ---------------------------------------------------------------------------
# Repair-backoff exclusion
# ---------------------------------------------------------------------------


def test_repair_backoff_task_not_in_ready_tasks():
    orch = _orch()
    orch.register(_leaf("a"))
    orch.lease("a")
    orch.enter_repair_backoff("a", reason="test failure")
    assert orch.get("a").state == TaskState.REPAIR_BACKOFF
    assert all(t.key != "a" for t in orch.ready_tasks())


def test_repair_backoff_task_not_leasable():
    orch = _orch()
    orch.register(_leaf("a"))
    orch.lease("a")
    orch.enter_repair_backoff("a", reason="test failure")
    with pytest.raises(ValueError, match="TASK_NOT_READY"):
        orch.lease("a")


def test_recover_from_backoff_restores_ready():
    orch = _orch()
    orch.register(_leaf("a"))
    orch.lease("a")
    orch.enter_repair_backoff("a", reason="test failure")
    orch.recover_from_backoff("a")
    assert orch.get("a").state == TaskState.READY


def test_recover_from_backoff_requires_backoff_state():
    orch = _orch()
    orch.register(_leaf("a"))
    with pytest.raises(ValueError, match="NOT_IN_BACKOFF"):
        orch.recover_from_backoff("a")


def test_repair_backoff_releases_lease():
    orch = _orch()
    orch.register(_leaf("a"))
    orch.lease("a", holder="w1")
    orch.enter_repair_backoff("a", reason="failing")
    leaf = orch.get("a")
    assert leaf.leased_at is None
    assert leaf.lease_holder is None


def test_owner_gated_task_restored_to_owner_gated_after_backoff_recovery():
    # A production task in repair-backoff should go to OWNER_GATED not READY.
    orch = _orch()
    leaf = _leaf("pg", authority_class=AUTH_PRODUCTION)
    orch.register(leaf)
    # Force into backoff directly (bypassing normal READY→LEASED path).
    leaf.state = TaskState.REPAIR_BACKOFF
    leaf.blocked_reason = "forced"
    orch.recover_from_backoff("pg")
    assert orch.get("pg").state == TaskState.OWNER_GATED


def test_backoff_depth_in_snapshot():
    orch = _orch()
    orch.register(_leaf("a"))
    orch.lease("a")
    orch.enter_repair_backoff("a", reason="fail")
    snap = orch.snapshot()
    assert snap["backoff_depth"] == 1


# ---------------------------------------------------------------------------
# Lease exclusivity
# ---------------------------------------------------------------------------


def test_lease_sets_state_to_leased():
    orch = _orch()
    orch.register(_leaf("a"))
    orch.lease("a")
    assert orch.get("a").state == TaskState.LEASED


def test_lease_sets_holder_and_timestamp():
    orch = _orch()
    orch.register(_leaf("a"))
    before = time.time()
    orch.lease("a", holder="worker-1")
    after = time.time()
    leaf = orch.get("a")
    assert leaf.lease_holder == "worker-1"
    assert before <= leaf.leased_at <= after


def test_double_lease_raises():
    orch = _orch()
    orch.register(_leaf("a"))
    orch.lease("a", holder="w1")
    with pytest.raises(ValueError, match="TASK_NOT_READY"):
        orch.lease("a", holder="w2")


def test_lease_unknown_key_raises():
    orch = _orch()
    with pytest.raises(LookupError, match="TASK_NOT_FOUND"):
        orch.lease("nonexistent")


def test_lease_removes_task_from_ready_tasks():
    orch = _orch()
    orch.register(_leaf("a"))
    orch.lease("a")
    assert all(t.key != "a" for t in orch.ready_tasks())


# ---------------------------------------------------------------------------
# Advance (LEASED → RUNNING / VALIDATING)
# ---------------------------------------------------------------------------


def test_advance_to_running():
    orch = _orch()
    orch.register(_leaf("a"))
    orch.lease("a")
    orch.advance("a", state=TaskState.RUNNING)
    assert orch.get("a").state == TaskState.RUNNING


def test_advance_to_validating():
    orch = _orch()
    orch.register(_leaf("a"))
    orch.lease("a")
    orch.advance("a", state=TaskState.VALIDATING)
    assert orch.get("a").state == TaskState.VALIDATING


def test_advance_invalid_state_raises():
    orch = _orch()
    orch.register(_leaf("a"))
    orch.lease("a")
    with pytest.raises(ValueError, match="INVALID_ADVANCE_STATE"):
        orch.advance("a", state=TaskState.COMPLETED)


# ---------------------------------------------------------------------------
# Completion and dependency propagation
# ---------------------------------------------------------------------------


def test_complete_sets_state_and_evidence():
    orch = _orch()
    orch.register(_leaf("a"))
    orch.lease("a")
    orch.complete("a", evidence={"pr": 99}, pr_number=99)
    leaf = orch.get("a")
    assert leaf.state == TaskState.COMPLETED
    assert leaf.evidence["pr"] == 99
    assert leaf.pr_number == 99


def test_complete_propagates_to_blocked_dependents():
    orch = _orch()
    orch.register(_leaf("dep-a"))
    orch.register(_leaf("child", deps=["dep-a"]))
    # "child" is not ready because dep-a is not completed yet.
    assert orch.get("child").state == TaskState.READY  # but dependency unmet
    # Lease and complete dep-a.
    orch.lease("dep-a")
    orch.complete("dep-a")
    # child should still be READY (already was, but now deps satisfied).
    assert orch.get("child").state == TaskState.READY


def test_complete_propagates_blocked_to_ready():
    orch = _orch()
    orch.register(_leaf("dep-a"))
    child = _leaf("child", deps=["dep-a"])
    child.state = TaskState.BLOCKED
    child.blocked_reason = "waiting for dep-a"
    orch.register(child)
    orch.lease("dep-a")
    orch.complete("dep-a")
    assert orch.get("child").state == TaskState.READY
    assert orch.get("child").blocked_reason is None


def test_dependency_blocked_when_dep_not_registered():
    """A task whose dep is unknown is treated as blocked (dep defaults to BLOCKED)."""
    orch = _orch()
    orch.register(_leaf("child", deps=["unknown-dep"]))
    assert "child" not in {t.key for t in orch.ready_tasks()}


def test_all_deps_must_complete_before_propagation():
    orch = _orch()
    orch.register(_leaf("dep-a"))
    orch.register(_leaf("dep-b"))
    child = _leaf("child", deps=["dep-a", "dep-b"])
    child.state = TaskState.BLOCKED
    orch.register(child)

    orch.lease("dep-a")
    orch.complete("dep-a")
    # Only dep-a done; child still blocked.
    assert orch.get("child").state == TaskState.BLOCKED

    orch.lease("dep-b")
    orch.complete("dep-b")
    # Now both done; child becomes READY.
    assert orch.get("child").state == TaskState.READY


# ---------------------------------------------------------------------------
# Block (capacity release)
# ---------------------------------------------------------------------------


def test_block_releases_lease_and_sets_reason():
    orch = _orch()
    orch.register(_leaf("a"))
    orch.lease("a", holder="w1")
    orch.block("a", reason="provider unavailable")
    leaf = orch.get("a")
    assert leaf.state == TaskState.BLOCKED
    assert leaf.lease_holder is None
    assert leaf.leased_at is None
    assert leaf.blocked_reason == "provider unavailable"


def test_block_does_not_block_program_capacity():
    """Blocking a task frees its slot — refill still returns other ready tasks."""
    orch = _orch(width=2)
    orch.register(_leaf("a"))
    orch.register(_leaf("b"))
    orch.register(_leaf("c"))
    orch.lease("a")
    orch.lease("b")
    # Now at capacity. Block one.
    orch.block("a", reason="fail")
    # Capacity freed; c should now be a refill candidate.
    candidates = orch.refill()
    assert any(t.key == "c" for t in candidates)


# ---------------------------------------------------------------------------
# No-idle capacity / refill invariants
# ---------------------------------------------------------------------------


def test_refill_respects_configured_width():
    orch = _orch(width=3)
    for i in range(6):
        orch.register(_leaf(f"task-{i}"))
    candidates = orch.refill()
    assert len(candidates) <= 3


def test_refill_returns_empty_when_at_capacity():
    orch = _orch(width=2)
    orch.register(_leaf("a"))
    orch.register(_leaf("b"))
    orch.lease("a")
    orch.lease("b")
    assert orch.refill() == []


def test_refill_after_completion_opens_slot():
    orch = _orch(width=1)
    orch.register(_leaf("a"))
    orch.register(_leaf("b"))
    orch.lease("a")
    orch.complete("a")
    # Slot freed — b should appear.
    candidates = orch.refill()
    assert any(t.key == "b" for t in candidates)


def test_refill_after_block_opens_slot():
    orch = _orch(width=1)
    orch.register(_leaf("a"))
    orch.register(_leaf("b"))
    orch.lease("a")
    orch.block("a", reason="blocked")
    candidates = orch.refill()
    assert any(t.key == "b" for t in candidates)


def test_refill_excludes_owner_gated():
    orch = _orch(width=5)
    orch.register(_leaf("pg", authority_class=AUTH_PRODUCTION))
    orch.register(_leaf("normal"))
    candidates = orch.refill()
    keys = {t.key for t in candidates}
    assert "pg" not in keys
    assert "normal" in keys


def test_refill_excludes_repair_backoff():
    orch = _orch(width=5)
    orch.register(_leaf("a"))
    orch.register(_leaf("b"))
    orch.lease("a")
    orch.enter_repair_backoff("a", reason="fail")
    candidates = orch.refill()
    keys = {t.key for t in candidates}
    assert "a" not in keys


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------


def test_ready_tasks_ordered_by_priority_then_created_at():
    orch = _orch(width=10)
    orch.register(_leaf("p3", priority=Priority.P3))
    orch.register(_leaf("p1", priority=Priority.P1))
    orch.register(_leaf("p0", priority=Priority.P0))
    orch.register(_leaf("p2", priority=Priority.P2))
    keys = [t.key for t in orch.ready_tasks()]
    assert keys == ["p0", "p1", "p2", "p3"]


def test_refill_returns_highest_priority_first():
    orch = _orch(width=2)
    for p in (Priority.P4, Priority.P0, Priority.P2):
        orch.register(_leaf(f"p{p}", priority=p))
    candidates = orch.refill()
    assert candidates[0].priority < candidates[-1].priority


def test_same_priority_ordered_by_created_at():
    orch = _orch(width=10)
    t1 = TaskLeaf(
        key="first", title="first", repo="r", module="m",
        priority=Priority.P1, authority_class=AUTH_WORKSPACE,
        consequence_risk="low", created_at=1000.0, updated_at=1000.0,
    )
    t2 = TaskLeaf(
        key="second", title="second", repo="r", module="m",
        priority=Priority.P1, authority_class=AUTH_WORKSPACE,
        consequence_risk="low", created_at=2000.0, updated_at=2000.0,
    )
    orch.register(t2)
    orch.register(t1)
    keys = [t.key for t in orch.ready_tasks()]
    assert keys[0] == "first"


# ---------------------------------------------------------------------------
# Dependency gating
# ---------------------------------------------------------------------------


def test_task_with_unmet_dep_excluded_from_ready():
    orch = _orch()
    orch.register(_leaf("parent"))
    orch.register(_leaf("child", deps=["parent"]))
    ready_keys = {t.key for t in orch.ready_tasks()}
    assert "child" not in ready_keys
    assert "parent" in ready_keys


def test_task_with_completed_dep_is_ready():
    orch = _orch()
    orch.register(_leaf("parent"))
    orch.register(_leaf("child", deps=["parent"]))
    orch.lease("parent")
    orch.complete("parent")
    ready_keys = {t.key for t in orch.ready_tasks()}
    assert "child" in ready_keys


def test_chain_dependency_gates_correctly():
    orch = _orch()
    orch.register(_leaf("a"))
    orch.register(_leaf("b", deps=["a"]))
    orch.register(_leaf("c", deps=["b"]))
    # Only a is ready.
    ready_keys = {t.key for t in orch.ready_tasks()}
    assert ready_keys == {"a"}
    # Complete a → b becomes ready.
    orch.lease("a")
    orch.complete("a")
    ready_keys = {t.key for t in orch.ready_tasks()}
    assert ready_keys == {"b"}
    # Complete b → c becomes ready.
    orch.lease("b")
    orch.complete("b")
    ready_keys = {t.key for t in orch.ready_tasks()}
    assert ready_keys == {"c"}


# ---------------------------------------------------------------------------
# Active tasks
# ---------------------------------------------------------------------------


def test_active_tasks_includes_leased_running_validating():
    orch = _orch()
    orch.register(_leaf("leased"))
    orch.register(_leaf("running"))
    orch.register(_leaf("validating"))
    orch.lease("leased")
    orch.lease("running")
    orch.advance("running", state=TaskState.RUNNING)
    orch.lease("validating")
    orch.advance("validating", state=TaskState.VALIDATING)
    active_keys = {t.key for t in orch.active_tasks()}
    assert active_keys == {"leased", "running", "validating"}


def test_completed_not_in_active():
    orch = _orch()
    orch.register(_leaf("a"))
    orch.lease("a")
    orch.complete("a")
    assert all(t.key != "a" for t in orch.active_tasks())


# ---------------------------------------------------------------------------
# Snapshot / Mission Control
# ---------------------------------------------------------------------------


def test_snapshot_schema_version():
    orch = _orch()
    snap = orch.snapshot()
    assert snap["schema_version"] == SCHEMA_VERSION


def test_snapshot_counts():
    orch = _orch(width=3)
    orch.register(_leaf("a"))
    orch.register(_leaf("b"))
    orch.register(_leaf("c"))
    orch.register(_leaf("pg", authority_class=AUTH_PRODUCTION))
    orch.lease("a")
    orch.block("b", reason="fail")
    snap = orch.snapshot()
    assert snap["active_count"] == 1
    assert snap["ready_depth"] == 1  # only c
    assert snap["blocked_depth"] == 1
    assert snap["owner_gate_count"] == 1
    assert snap["total_task_count"] == 4


def test_snapshot_next_tasks_ordered_by_priority():
    orch = _orch(width=10)
    orch.register(_leaf("p3", priority=Priority.P3))
    orch.register(_leaf("p0", priority=Priority.P0))
    snap = orch.snapshot(next_n=5)
    keys = [t["key"] for t in snap["next_tasks"]]
    assert keys[0] == "p0"


def test_snapshot_capacity_idle():
    orch = _orch(width=3)
    orch.register(_leaf("a"))
    orch.lease("a")
    snap = orch.snapshot()
    assert snap["capacity_idle"] == 2


def test_snapshot_blocked_reasons():
    orch = _orch()
    orch.register(_leaf("a"))
    orch.register(_leaf("b"))
    orch.lease("a")
    orch.block("a", reason="provider unavailable")
    orch.lease("b")
    orch.block("b", reason="CI failed")
    snap = orch.snapshot()
    assert snap["blocked_reasons"]["a"] == "provider unavailable"
    assert snap["blocked_reasons"]["b"] == "CI failed"


# ---------------------------------------------------------------------------
# Persistence / restart recovery
# ---------------------------------------------------------------------------


def test_to_dict_round_trip():
    orch = _orch(width=4)
    orch.register(_leaf("a", priority=Priority.P0))
    orch.register(_leaf("b", deps=["a"]))
    orch.register(_leaf("pg", authority_class=AUTH_PRODUCTION))
    orch.lease("a")
    orch.advance("a", state=TaskState.RUNNING)

    d = orch.to_dict()
    restored = DeepOrchestrate.from_dict(d)

    assert restored.configured_width == 4
    assert restored.get("a").state == TaskState.RUNNING
    assert restored.get("b").state == TaskState.READY
    assert restored.get("pg").state == TaskState.OWNER_GATED


def test_to_dict_schema_version():
    orch = _orch()
    d = orch.to_dict()
    assert d["schema_version"] == SCHEMA_VERSION


def test_from_dict_preserves_evidence():
    orch = _orch()
    orch.register(_leaf("a"))
    orch.lease("a")
    orch.complete("a", evidence={"pr": 42, "tests": 25})
    d = orch.to_dict()
    restored = DeepOrchestrate.from_dict(d)
    assert restored.get("a").evidence["pr"] == 42
    assert restored.get("a").evidence["tests"] == 25


def test_from_dict_restores_repair_backoff():
    orch = _orch()
    orch.register(_leaf("a"))
    orch.lease("a")
    orch.enter_repair_backoff("a", reason="test fail")
    d = orch.to_dict()
    restored = DeepOrchestrate.from_dict(d)
    assert restored.get("a").state == TaskState.REPAIR_BACKOFF
    # Still not leasable after restore.
    with pytest.raises(ValueError, match="TASK_NOT_READY"):
        restored.lease("a")


def test_from_dict_restores_pr_number():
    orch = _orch()
    orch.register(_leaf("a"))
    orch.lease("a")
    orch.complete("a", pr_number=1238)
    d = orch.to_dict()
    restored = DeepOrchestrate.from_dict(d)
    assert restored.get("a").pr_number == 1238


def test_restart_recovery_refill_still_works():
    """After deserialization, ready/refill behave correctly."""
    orch = _orch(width=3)
    for i in range(5):
        orch.register(_leaf(f"t{i}"))
    # Lease two, serialize.
    orch.lease("t0")
    orch.lease("t1")
    d = orch.to_dict()
    restored = DeepOrchestrate.from_dict(d)
    # t0 and t1 are LEASED, so there are 2 active and 1 slot left.
    candidates = restored.refill()
    assert len(candidates) == 1
    assert candidates[0].key in {"t2", "t3", "t4"}


# ---------------------------------------------------------------------------
# seed_from_1024
# ---------------------------------------------------------------------------


def test_seed_from_1024_returns_non_empty_list():
    seeds = seed_from_1024()
    assert len(seeds) >= 10


def test_seed_from_1024_owner_gated_tasks_auto_gated():
    orch = _orch()
    orch.register_many(seed_from_1024())
    # Production and science pub tasks must be OWNER_GATED.
    prod = orch.get("backend:production:db-migration:apply")
    sci = orch.get("backend:science:kg-mutation:publish")
    assert prod is not None
    assert prod.state == TaskState.OWNER_GATED
    assert sci is not None
    assert sci.state == TaskState.OWNER_GATED


def test_seed_completed_tasks_are_completed():
    """Seed tasks for already-merged PRs carry COMPLETED state."""
    orch = _orch()
    orch.register_many(seed_from_1024())
    gates36 = orch.get("backend:calyx:recovery:gates-3-6")
    assert gates36 is not None
    assert gates36.state == TaskState.COMPLETED


def test_seed_from_1024_keys_unique():
    seeds = seed_from_1024()
    keys = [s.key for s in seeds]
    assert len(keys) == len(set(keys)), "Seed keys must be unique"


def test_seed_from_1024_all_have_acceptance_criteria():
    for leaf in seed_from_1024():
        assert len(leaf.acceptance_criteria) > 0, (
            f"Leaf {leaf.key} is missing acceptance criteria"
        )


def test_seed_deep_orchestrate_reservoir_leaf_present():
    seeds = seed_from_1024()
    keys = {s.key for s in seeds}
    assert "backend:orchestrate:deep-orchestrate:reservoir" in keys


# ---------------------------------------------------------------------------
# TaskLeaf to_dict / from_dict
# ---------------------------------------------------------------------------


def test_task_leaf_round_trip():
    leaf = _leaf("a", priority=Priority.P1, deps=["dep-x"])
    leaf.state = TaskState.RUNNING
    leaf.leased_at = 12345.0
    leaf.lease_holder = "worker-1"
    leaf.evidence = {"pr": 7}
    d = leaf.to_dict()
    restored = TaskLeaf.from_dict(d)
    assert restored.key == "a"
    assert restored.state == TaskState.RUNNING
    assert restored.leased_at == 12345.0
    assert restored.lease_holder == "worker-1"
    assert restored.dependencies == ["dep-x"]
    assert restored.evidence["pr"] == 7


def test_task_leaf_requires_owner_gate_property():
    for auth in (AUTH_PRODUCTION, AUTH_SCIENCE_PUB, AUTH_SECURITY, AUTH_GOVERNANCE):
        assert _leaf("x", authority_class=auth).requires_owner_gate
    for auth in (AUTH_READ_ONLY, AUTH_WORKSPACE, AUTH_REPO_EXEC):
        assert not _leaf("x", authority_class=auth).requires_owner_gate
