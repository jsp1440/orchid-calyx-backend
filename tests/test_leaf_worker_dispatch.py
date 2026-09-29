"""Tests: leaf-worker dispatch vertical slice.

Covers all 14 required proofs for Phase 2:
1.  READY task leases successfully
2.  Same task cannot be leased twice (atomic lease safety)
3.  Dependency blocks downstream execution
4.  Completion releases eligible dependent
5.  Independent tasks can be leased concurrently (parallelism proof)
6.  Resource conflict prevents unsafe parallel lease
7.  OWNER_GATED task never auto-executes
8.  Successful worker calls complete()
9.  Failed/blocked worker follows canonical block() path
10. Completed work is not executed again (idempotency)
11. Duplicate complete() is idempotent
12. Expired/abandoned lease can recover (crash-safety)
13. Bounded dispatcher terminates within limits
14. Full provider-free integration: governance → blueprint → queue → worker → terminal
"""
from __future__ import annotations

import threading
import time

import pytest

from app.calyx_orchestrator.bounded_dispatcher import (
    BoundedDispatcher,
    DispatchConfig,
    DispatchRun,
)
from app.calyx_orchestrator.deep_orchestrate import (
    AUTH_GOVERNANCE,
    AUTH_PRODUCTION,
    AUTH_SCIENCE_PUB,
    AUTH_SECURITY,
    AUTH_WORKSPACE,
    DeepOrchestrate,
    Priority,
    TaskLeaf,
    TaskState,
)
from app.calyx_orchestrator.leaf_worker import (
    WORKER_ID,
    DeterministicResearchWorker,
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
    resources: list[str] | None = None,
    step: str = "retrieve-evidence",
) -> TaskLeaf:
    return TaskLeaf(
        key=key,
        title=f"Task {key}",
        repo="orchid-calyx-backend",
        module="app/test",
        priority=priority,
        authority_class=authority_class,
        consequence_risk=consequence_risk,
        dependencies=deps or [],
        resources=resources or [],
    )


def _leaf_with_step(key: str, step: str, **kwargs) -> TaskLeaf:
    """Leaf whose key embeds a recognizable step name for worker dispatch."""
    full_key = f"research:0102030405060708:{step}"
    return TaskLeaf(
        key=full_key,
        title=f"Task {full_key}",
        repo="orchid-calyx-backend",
        module="app/test",
        priority=Priority.P2,
        authority_class=kwargs.get("authority_class", AUTH_WORKSPACE),
        consequence_risk=kwargs.get("consequence_risk", "low"),
        dependencies=kwargs.get("deps", []),
        resources=kwargs.get("resources", []),
    )


def _orch(width: int = 5) -> DeepOrchestrate:
    return DeepOrchestrate(configured_width=width)


def _worker() -> DeterministicResearchWorker:
    return DeterministicResearchWorker()


# ---------------------------------------------------------------------------
# 1. READY task leases successfully
# ---------------------------------------------------------------------------


def test_ready_task_leases_successfully():
    orch = _orch()
    leaf = _leaf("research:aabbccdd01020304:retrieve-evidence")
    orch.register(leaf)
    orch.refill()
    leased = orch.lease("research:aabbccdd01020304:retrieve-evidence")
    assert leased.state == TaskState.LEASED
    assert leased.lease_holder == "claude"


# ---------------------------------------------------------------------------
# 2. Same task cannot be leased twice (atomic lease safety)
# ---------------------------------------------------------------------------


def test_same_task_cannot_be_leased_twice():
    orch = _orch()
    key = "research:aabbccdd01020304:retrieve-evidence"
    orch.register(_leaf(key))
    orch.refill()
    orch.lease(key)
    with pytest.raises((ValueError, LookupError)):
        orch.lease(key)


def test_concurrent_lease_only_one_succeeds():
    """Prove lease is thread-safe: only one thread acquires the lease."""
    orch = _orch(width=10)
    key = "research:aabbccdd01020304:retrieve-evidence"
    orch.register(_leaf(key))
    orch.refill()

    successes: list[str] = []
    errors: list[Exception] = []
    barrier = threading.Barrier(8)

    def try_lease():
        barrier.wait()
        try:
            orch.lease(key, holder="t")
            successes.append("ok")
        except (ValueError, LookupError) as exc:
            errors.append(exc)

    threads = [threading.Thread(target=try_lease) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(successes) == 1
    assert len(errors) == 7


# ---------------------------------------------------------------------------
# 3. Dependency blocks downstream execution
# ---------------------------------------------------------------------------


def test_dependency_blocks_downstream():
    orch = _orch()
    orch.register(_leaf("step-a"))
    orch.register(_leaf("step-b", deps=["step-a"]))
    orch.refill()

    ready_keys = {t.key for t in orch.ready_tasks()}
    assert "step-a" in ready_keys
    assert "step-b" not in ready_keys


# ---------------------------------------------------------------------------
# 4. Completion releases eligible dependent
# ---------------------------------------------------------------------------


def test_completion_releases_dependent():
    orch = _orch()
    orch.register(_leaf("step-a"))
    orch.register(_leaf("step-b", deps=["step-a"]))
    orch.refill()

    orch.lease("step-a")
    orch.complete("step-a", evidence={"done": True})
    orch.refill()

    ready_keys = {t.key for t in orch.ready_tasks()}
    assert "step-b" in ready_keys


# ---------------------------------------------------------------------------
# 5. Independent tasks can be leased concurrently (parallelism proof)
# ---------------------------------------------------------------------------


def test_independent_tasks_leased_concurrently():
    """A and B have no deps; both can be leased without conflict."""
    orch = _orch(width=5)
    orch.register(_leaf("task-a"))
    orch.register(_leaf("task-b"))
    orch.refill()

    la = orch.lease("task-a", holder="worker-1")
    lb = orch.lease("task-b", holder="worker-2")
    assert la.state == TaskState.LEASED
    assert lb.state == TaskState.LEASED


def test_diamond_dep_c_waits_for_both_a_and_b():
    """Parallelism proof: A ‖ B → C; C waits for both."""
    orch = _orch(width=5)
    orch.register(_leaf("a"))
    orch.register(_leaf("b"))
    orch.register(_leaf("c", deps=["a", "b"]))
    orch.refill()

    ready_keys = {t.key for t in orch.ready_tasks()}
    assert "a" in ready_keys
    assert "b" in ready_keys
    assert "c" not in ready_keys

    orch.lease("a")
    orch.complete("a", evidence={})
    orch.refill()
    ready_keys = {t.key for t in orch.ready_tasks()}
    assert "c" not in ready_keys  # B still incomplete

    orch.lease("b")
    orch.complete("b", evidence={})
    orch.refill()
    ready_keys = {t.key for t in orch.ready_tasks()}
    assert "c" in ready_keys  # Now C is eligible


# ---------------------------------------------------------------------------
# 6. Resource conflict prevents unsafe parallel lease
# ---------------------------------------------------------------------------


def test_resource_conflict_blocks_second_lease():
    """Exclusive resource: only one task can hold it at a time."""
    orch = _orch(width=5)
    orch.register(_leaf("task-x", resources=["kg:taxon:orchids"]))
    orch.register(_leaf("task-y", resources=["kg:taxon:orchids"]))
    orch.refill()

    orch.lease("task-x", holder="worker-x")
    with pytest.raises(ValueError, match="RESOURCE_CONFLICT"):
        orch.lease("task-y", holder="worker-y")


def test_non_overlapping_resources_lease_concurrently():
    """Different resources → no conflict."""
    orch = _orch(width=5)
    orch.register(_leaf("task-m", resources=["resource:alpha"]))
    orch.register(_leaf("task-n", resources=["resource:beta"]))
    orch.refill()

    lm = orch.lease("task-m", holder="worker-m")
    ln = orch.lease("task-n", holder="worker-n")
    assert lm.state == TaskState.LEASED
    assert ln.state == TaskState.LEASED


# ---------------------------------------------------------------------------
# 7. OWNER_GATED tasks never auto-execute
# ---------------------------------------------------------------------------


def test_owner_gated_task_skipped_by_dispatcher():
    orch = _orch()
    # AUTH_PRODUCTION forces OWNER_GATED state
    orch.register(_leaf("prod-task", authority_class=AUTH_PRODUCTION))
    orch.refill()

    dispatcher = BoundedDispatcher(orch)
    run = dispatcher.run(DispatchConfig(max_tasks=5))
    assert run.tasks_executed == 0
    assert all(k != "prod-task" for r in run.results for k in [r.task_key])


def test_worker_rejects_owner_gated_authority():
    """Worker.execute() itself rejects high-authority leaves."""
    worker = _worker()
    for auth in [AUTH_PRODUCTION, AUTH_SCIENCE_PUB, AUTH_SECURITY, AUTH_GOVERNANCE]:
        leaf = TaskLeaf(
            key=f"leaf-{auth}",
            title="owner-gated",
            repo="r",
            module="m",
            priority=Priority.P2,
            authority_class=auth,
            consequence_risk="high",
        )
        result = worker.execute(leaf)
        assert result.status == "blocked"
        assert result.error_reason == "OWNER_GATE_REQUIRED"


# ---------------------------------------------------------------------------
# 8. Successful worker execution calls complete()
# ---------------------------------------------------------------------------


def test_successful_worker_completes_task():
    orch = _orch()
    key = "research:aabb000011223344:retrieve-evidence"
    orch.register(_leaf(key))
    orch.refill()

    leaf = orch.lease(key)
    worker = _worker()
    result = worker.execute(leaf)

    assert result.status == "completed"
    assert result.output.get("provider_api_called") is False

    orch.complete(key, evidence=result.as_evidence())
    task = orch._tasks[key]
    assert task.state == TaskState.COMPLETED


# ---------------------------------------------------------------------------
# 9. Failed/blocked worker follows canonical block() path
# ---------------------------------------------------------------------------


def test_unknown_step_blocks_via_canonical_path():
    orch = _orch()
    key = "research:aabb000011223344:unknown-step-xyz"
    orch.register(_leaf(key))
    orch.refill()

    leaf = orch.lease(key)
    worker = _worker()
    result = worker.execute(leaf)

    assert result.status == "blocked"
    assert "UNKNOWN_TASK_STEP" in (result.error_reason or "")

    orch.block(key, reason=result.error_reason or "WORKER_BLOCKED")
    task = orch._tasks[key]
    assert task.state == TaskState.BLOCKED


# ---------------------------------------------------------------------------
# 10. Completed work is not executed again (idempotency / crash-safety)
# ---------------------------------------------------------------------------


def test_completed_task_not_leased_again():
    orch = _orch()
    key = "research:aabb000011223344:retrieve-evidence"
    orch.register(_leaf(key))
    orch.refill()
    orch.lease(key)
    orch.complete(key, evidence={"ok": True})

    with pytest.raises((ValueError, LookupError)):
        orch.lease(key)


def test_dispatcher_skips_already_completed_tasks():
    orch = _orch()
    key = "research:aabb000011223344:retrieve-evidence"
    orch.register(_leaf(key))
    orch.refill()

    # Manually complete before dispatcher runs.
    orch.lease(key, holder="pre-run")
    orch.complete(key, evidence={"pre": True})

    dispatcher = BoundedDispatcher(orch)
    run = dispatcher.run(DispatchConfig(max_tasks=5))
    # The task is already completed; dispatcher should not execute it.
    assert not any(r.task_key == key for r in run.results)


# ---------------------------------------------------------------------------
# 11. Duplicate complete() is idempotent
# ---------------------------------------------------------------------------


def test_duplicate_complete_is_idempotent():
    """complete() on an already-COMPLETED task is a no-op: state stays COMPLETED."""
    orch = _orch()
    key = "research:aabb000011223344:retrieve-evidence"
    orch.register(_leaf(key))
    orch.refill()
    orch.lease(key)
    orch.complete(key, evidence={"round": 1})
    # Second complete does not crash; state stays COMPLETED.
    orch.complete(key, evidence={"round": 2})
    assert orch._tasks[key].state == TaskState.COMPLETED


# ---------------------------------------------------------------------------
# 12. Expired/abandoned lease can recover (crash-safety)
# ---------------------------------------------------------------------------


def test_expired_lease_recovers_to_repair_backoff():
    orch = _orch()
    key = "research:aabb000011223344:retrieve-evidence"
    orch.register(_leaf(key))
    orch.refill()

    leaf = orch.lease(key)
    # Simulate lease age > threshold.
    leaf.leased_at = time.time() - 400

    recovered = orch.recover_expired_leases(max_lease_age_seconds=300.0)
    assert len(recovered) == 1
    assert recovered[0].key == key
    assert orch._tasks[key].state == TaskState.REPAIR_BACKOFF


def test_unexpired_lease_not_recovered():
    orch = _orch()
    key = "research:aabb000011223344:retrieve-evidence"
    orch.register(_leaf(key))
    orch.refill()
    orch.lease(key)  # fresh lease

    recovered = orch.recover_expired_leases(max_lease_age_seconds=300.0)
    assert len(recovered) == 0
    assert orch._tasks[key].state == TaskState.LEASED


# ---------------------------------------------------------------------------
# 13. Bounded dispatcher terminates within configured limits
# ---------------------------------------------------------------------------


def test_dispatcher_terminates_no_tasks():
    orch = _orch()
    run = BoundedDispatcher(orch).run(DispatchConfig(max_tasks=10, max_iterations=5))
    assert isinstance(run, DispatchRun)
    assert run.iterations <= 5


def test_dispatcher_respects_max_tasks():
    orch = _orch(width=10)
    for i in range(20):
        orch.register(_leaf(f"research:aabb{i:012d}:retrieve-evidence"))
    orch.refill()

    run = BoundedDispatcher(orch).run(DispatchConfig(max_tasks=3, max_iterations=10))
    assert run.tasks_executed <= 3


def test_dispatcher_terminates_when_no_ready_work():
    orch = _orch()
    # Register leaf that depends on uncompleted parent — nothing becomes READY.
    orch.register(_leaf("parent"))
    orch.register(_leaf("child", deps=["parent"]))
    orch.refill()

    # Lease parent but don't complete it.
    orch.lease("parent", holder="blocker")

    run = BoundedDispatcher(orch).run(DispatchConfig(max_tasks=10, max_iterations=5))
    # child was never leased; dispatcher found no ready work and stopped.
    assert run.tasks_executed == 0
    assert run.iterations <= 5


# ---------------------------------------------------------------------------
# 14. Full provider-free integration: governance → blueprint → queue → worker
# ---------------------------------------------------------------------------


def test_full_provider_free_integration_cycle():
    """End-to-end: GovernanceDecision(admitted) → blueprint decompose → enqueue
    → lease → worker.execute() → complete() → next task eligible → terminal.

    Provider-free: no API call, no model inference, no network.
    """
    from app.scientific_synthesis.blueprint import (
        decompose_governed_action,
        enqueue_blueprint,
    )
    from app.scientific_synthesis.governance import (
        GovernanceDecision,
        GovernanceOutcome,
    )
    from app.scientific_synthesis.run_manifest import (
        MANIFEST_VERSION,
        build_run_evidence_manifest,
    )

    # --- Build a minimal manifest ----------------------------------------
    _packet = {
        "contract_version": "oc-verification-handoff-v1",
        "verification_state": "ready_for_review",
        "reasoning": {
            "contract_version": "oc-parallel-v1",
            "candidate_knowledge": {
                "candidate_id": "candidate:e2e-test",
                "subject_id": "taxon:orchidaceae",
                "predicate": "grows_at",
                "object_id": "temperature:intermediate",
                "evidence_ids": ["ev-1"],
                "confidence": 0.75,
                "review_state": "candidate",
            },
            "contradictions": [],
            "validation_pathways": ["taxonomist_review"],
            "human_review_required": True,
            "automatic_scientific_publication_allowed": False,
            "private_chain_of_thought_stored": False,
        },
        "resolved_evidence": [
            {
                "evidence_id": "ev-1",
                "source_id": "src-1",
                "statement": "X increases orchid growth.",
                "provenance": ["doi:10.0000/test"],
                "confidence": 0.80,
            }
        ],
        "missing_evidence_ids": [],
        "knowledge_gaps": [],
        "contradictions": [],
        "human_review_required": True,
        "automatic_scientific_publication_allowed": False,
    }
    manifest_dict = build_run_evidence_manifest(
        run_id="run-e2e-001",
        research_question="What is the effect of X on orchid growth?",
        taxon_id="taxon:orchidaceae",
        taxonomy_snapshot_id="snap-001",
        verification_packets=(_packet,),
        review_records=(),
        epistemic_memory_entries=(),
    )
    assert manifest_dict.get("contract_version") == MANIFEST_VERSION

    # --- Governance decision (admitted) -----------------------------------
    decision = GovernanceDecision(
        outcome=GovernanceOutcome.ADMITTED,
        admitted=True,
        reason="All governance flags clear",
        blocking_flags=[],
    )

    # --- Blueprint decomposition ------------------------------------------
    blueprint = decompose_governed_action(
        decision,
        manifest_dict,
        "build_synthesis",
        run_id="run-e2e-001",
        taxon_id="taxon:orchidaceae",
        research_question="What is the effect of X on orchid growth?",
    )
    from app.scientific_synthesis.governance import GovernanceOutcome
    assert blueprint.governance_outcome == GovernanceOutcome.ADMITTED
    assert len(blueprint.task_leaves) >= 1

    # --- Enqueue into DeepOrchestrate -------------------------------------
    orch = DeepOrchestrate(configured_width=8)
    enqueue_blueprint(blueprint, orch)

    # All leaves registered; at least some should be READY or OWNER_GATED.
    all_states = {t.state for t in orch._tasks.values()}
    assert TaskState.READY in all_states or len(orch._tasks) > 0

    # --- Run bounded dispatcher ------------------------------------------
    worker = DeterministicResearchWorker()
    dispatcher = BoundedDispatcher(orch, worker=worker)
    run = dispatcher.run(DispatchConfig(max_tasks=20, max_iterations=15))

    # At least one task executed (or all owner-gated — check non-gated leaves).
    non_gated = [
        t for t in orch._tasks.values()
        if t.authority_class not in {
            "production_change",
            "scientific_publication",
            "restricted_data_or_security",
            "governance_change",
        }
    ]
    if non_gated:
        assert run.tasks_executed >= 1

    # --- Verify no paid API was called ------------------------------------
    for result in run.results:
        output = result.output
        assert output.get("provider_api_called") is False, (
            f"provider_api_called is True for task {result.task_key}"
        )
        assert output.get("fabrication_attempted", False) is False

    # --- Verify completed tasks are truly terminal -----------------------
    for result in run.results:
        if result.status == "completed":
            task = orch._tasks[result.task_key]
            assert task.state == TaskState.COMPLETED

    # --- Verify OWNER_GATED tasks were never auto-executed ---------------
    owner_gated_tasks = [
        t for t in orch._tasks.values()
        if t.state == TaskState.OWNER_GATED
    ]
    executed_keys = {r.task_key for r in run.results}
    for t in owner_gated_tasks:
        assert t.key not in executed_keys, (
            f"OWNER_GATED task {t.key} was auto-executed — governance violated"
        )

    # --- Summary is well-formed ------------------------------------------
    summary = run.summary()
    assert "tasks_executed" in summary
    assert "results" in summary
    assert summary["completed"] + summary["blocked"] == run.tasks_executed


# ---------------------------------------------------------------------------
# TaskExecutionResult contract tests
# ---------------------------------------------------------------------------


def test_task_execution_result_as_evidence_is_serializable():
    """as_evidence() returns a plain dict with no non-serializable objects."""
    import json

    orch = _orch()
    key = "research:aabb000011223344:retrieve-evidence"
    orch.register(_leaf(key))
    orch.refill()
    leaf = orch.lease(key)

    result = _worker().execute(leaf)
    evidence = result.as_evidence()
    # Must be JSON-serializable.
    serialized = json.dumps(evidence)
    assert "task_key" in serialized
    assert "worker_id" in serialized


def test_worker_id_is_canonical():
    """Worker reports its canonical deterministic identity."""
    worker = _worker()
    assert worker.worker_id == WORKER_ID
    assert WORKER_ID == "deterministic-research-worker-v1"


def test_all_non_gated_steps_complete_not_blocked():
    """Each recognized step name produces a completed result."""
    steps = [
        "retrieve-evidence",
        "normalize-evidence",
        "assess-contradictions",
        "produce-synthesis-artifact",
        "run-verification",
        "submit-for-human-review",
        "submit-human-review-record",
        "build-run-manifest",
    ]
    worker = _worker()
    for step in steps:
        leaf = TaskLeaf(
            key=f"research:aabb000011223344:{step}",
            title=step,
            repo="r",
            module="m",
            priority=Priority.P2,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
        )
        result = worker.execute(leaf)
        assert result.status == "completed", (
            f"Step '{step}' blocked unexpectedly: {result.error_reason}"
        )
        assert result.output.get("provider_api_called") is False


# ---------------------------------------------------------------------------
# Regression: authorized OWNER_GATED tasks ARE dispatched (was: skipped)
# ---------------------------------------------------------------------------


def test_authorized_owner_gated_task_is_dispatched():
    """Regression: reservoir.authorize() moves task OWNER_GATED → READY.
    After authorization the dispatcher MUST execute the task, not skip it.

    Bug: _collect_ready_keys() was checking leaf.authority_class in
    _OWNER_GATE_CLASSES, which permanently blocked AUTH_PRODUCTION tasks even
    after they were explicitly authorized via reservoir.authorize(). The fix
    checks leaf.state == OWNER_GATED instead (ready_tasks() only returns READY
    leaves, so this is a belt-and-suspenders guard only).
    """
    from app.calyx_orchestrator.bounded_dispatcher import (
        BoundedDispatcher,
        DispatchConfig,
    )
    from app.calyx_orchestrator.deep_orchestrate import (
        AUTH_PRODUCTION,
        AUTH_WORKSPACE,
        DeepOrchestrate,
        Priority,
        TaskLeaf,
        TaskState,
    )
    from app.calyx_orchestrator.leaf_worker import DeterministicResearchWorker

    res = DeepOrchestrate(configured_width=4)
    worker = DeterministicResearchWorker()

    ws = TaskLeaf(
        key="reg:t1:retrieve-evidence",
        title="ws",
        repo="r",
        module="m",
        priority=Priority.P1,
        authority_class=AUTH_WORKSPACE,
        consequence_risk="low",
    )
    og = TaskLeaf(
        key="reg:t2:canonical-mutation",
        title="og",
        repo="r",
        module="m",
        priority=Priority.P1,
        authority_class=AUTH_PRODUCTION,
        consequence_risk="high",
        dependencies=[ws.key],
    )
    res.register(ws)
    res.register(og)
    res.refill()

    # Initial dispatch: ws completes; og stays OWNER_GATED.
    d1 = BoundedDispatcher(res, worker=worker)
    run1 = d1.run(DispatchConfig(max_tasks=5, max_iterations=3))
    assert res.get(ws.key).state == TaskState.COMPLETED
    assert res.get(og.key).state == TaskState.OWNER_GATED
    assert run1.tasks_executed == 1

    # Explicitly authorize the OWNER_GATED task.
    res.authorize(og.key)
    assert res.get(og.key).state == TaskState.READY

    # Second dispatch: og is now READY and MUST be executed (not skipped).
    d2 = BoundedDispatcher(res, worker=worker)
    run2 = d2.run(DispatchConfig(max_tasks=5, max_iterations=3))
    assert run2.tasks_executed == 1, (
        f"Authorized OWNER_GATED task was skipped by dispatcher! "
        f"tasks_executed={run2.tasks_executed}, og state={res.get(og.key).state}"
    )
    assert res.get(og.key).state in (TaskState.COMPLETED, TaskState.BLOCKED), (
        f"og task stuck in unexpected state: {res.get(og.key).state}"
    )
