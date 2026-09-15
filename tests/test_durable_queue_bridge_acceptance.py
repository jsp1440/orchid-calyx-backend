"""Queue Bridge Acceptance Run #1 — machine-verifiable end-to-end proof.

Proves the complete Orchestrator Queue Bridge cycle:

  1. Source discovery    — legitimate work found from authoritative sources
  2. Normalization       — bridge maps leaves to reserve candidates
  3. Fingerprint stability — same input produces same fingerprint
  4. Deduplication       — unchanged fingerprint suppressed on second cycle
  5. Protected classification — AUTH_PRODUCTION never enters reserve
  6. Admission           — one safe, routine, provider-free item admitted
  7. Durable reservation — DurableOrchestrate.create_run + register (SQLite)
  8. Execution           — BoundedDispatcher + DeterministicResearchWorker
  9. Evidence persistence — all tasks COMPLETED; evidence recorded in reservoir
 10. Terminal state       — no orphaned LEASED or READY tasks
 11. Post-completion reconciliation — completed fingerprint suppresses re-admission
 12. Depletion refill     — new work source admitted after depletion
 13. Second unchanged cycle — refill candidate not duplicated on repeat run
 14. Zero paid provider calls — hard constraint throughout

Task keys use the "issue-NNN:step-name" pattern required by DeterministicResearchWorker.
Frontend issue numbers (660, 1264, 1085) are real oc-prepared/oc-queued items.

SQLite in-memory: no PostgreSQL or live Neon required. The PostgreSQL-specific
SELECT FOR UPDATE SKIP LOCKED path is covered by test_durable_reservoir_postgres.py.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.calyx_orchestrator.bounded_dispatcher import BoundedDispatcher, DispatchConfig
from app.calyx_orchestrator.deep_orchestrate import (
    AUTH_PRODUCTION,
    AUTH_WORKSPACE,
    DeepOrchestrate,
    Priority,
    TaskLeaf,
    TaskState,
)
from app.calyx_orchestrator.durable_reservoir import DurableOrchestrate
from app.calyx_orchestrator.durable_reservoir_models import DurableReservoirTask
from app.calyx_orchestrator.leaf_worker import DeterministicResearchWorker
from app.database import Base
from runtime.deep_orchestrate_queue_bridge import plan_deep_orchestrate_refill

# Canonical issue-to-task-step mapping for Queue Bridge Acceptance Run #1.
# Frontend issue → first executable DurableOrchestrate step.
_ISSUE_660_KEY = "issue-660:retrieve-evidence"   # Research Station → Matrix (#660)
_ISSUE_1264_KEY = "issue-1264:retrieve-evidence"  # Completion observer/healer (#1264)
_ISSUE_1085_KEY = "issue-1085:retrieve-evidence"  # Freshness backfill matrix (#1085)


def _sqlite_create_all(engine) -> None:
    tables = [t for t in Base.metadata.sorted_tables if t.schema is None]
    Base.metadata.create_all(engine, tables=tables)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine():
    e = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    _sqlite_create_all(e)
    yield e
    e.dispose()


@pytest.fixture()
def session(engine):
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    s = factory()
    yield s
    s.close()


@pytest.fixture()
def run_id():
    return f"qb-accept-{uuid.uuid4().hex[:12]}"


def _leaf(
    key: str,
    issue_number: int,
    *,
    priority: Priority = Priority.P2,
    authority_class: str = AUTH_WORKSPACE,
    consequence_risk: str = "low",
    deps: list[str] | None = None,
    completed: bool = False,
) -> TaskLeaf:
    leaf = TaskLeaf(
        key=key,
        title=f"Retrieve evidence for frontend issue #{issue_number}",
        repo="orchid-continuum-frontend",
        module="features/journeys",
        priority=priority,
        authority_class=authority_class,
        consequence_risk=consequence_risk,
        issue_number=issue_number,
        acceptance_criteria=["retrieve-evidence step completes provider-free"],
    )
    if deps:
        leaf.dependencies = deps
    if completed:
        leaf.state = TaskState.COMPLETED
    return leaf


def _snapshot(*issues: dict[str, Any], fingerprints: list[str] | None = None) -> dict[str, Any]:
    return {
        "issues": list(issues),
        "leases": [],
        "dispatch_fingerprints": list(fingerprints or []),
    }


# ---------------------------------------------------------------------------
# Phase 1-5: Source discovery, normalization, fingerprint, dedup, protected
# ---------------------------------------------------------------------------


def test_phase1_real_source_discovery_produces_proposal():
    """Frontend #660 (Research Station → Matrix) discovered as valid queue candidate.
    Proves: source discovery + normalization."""
    planner = DeepOrchestrate(configured_width=2)
    planner.register(_leaf(_ISSUE_660_KEY, 660, priority=Priority.P4))

    result = plan_deep_orchestrate_refill(planner, _snapshot(), reserve_depth=1)

    assert result["status"] == "refill_planned", result
    assert len(result["proposals"]) == 1
    proposal = result["proposals"][0]
    assert proposal["source_ref"] == "#660"
    assert proposal["queue_source_kind"] == "autonomous-orchestrator"
    assert proposal["semantic_key"] == f"deep-orchestrate:{_ISSUE_660_KEY}"
    assert result["provider_launch_authorized"] is False
    assert result["no_api_mode"] is True


def test_phase2_fingerprint_is_stable_across_repeated_planning():
    """Same leaf input produces identical material_fingerprint every time.
    Proves: fingerprint stability."""
    leaf = _leaf(_ISSUE_660_KEY, 660, priority=Priority.P4)

    planner_a = DeepOrchestrate(configured_width=2)
    planner_a.register(leaf)
    first = plan_deep_orchestrate_refill(planner_a, _snapshot(), reserve_depth=1)

    planner_b = DeepOrchestrate(configured_width=2)
    planner_b.register(leaf)
    second = plan_deep_orchestrate_refill(planner_b, _snapshot(), reserve_depth=1)

    assert first["proposals"][0]["material_fingerprint"] == second["proposals"][0]["material_fingerprint"]
    assert first["proposals"][0]["semantic_key"] == second["proposals"][0]["semantic_key"]


def test_phase3_unchanged_fingerprint_suppressed_on_second_cycle():
    """Second planning cycle with same fingerprint in snapshot produces zero new proposals.
    Proves: duplicate suppression (unchanged fingerprint → zero prepared items)."""
    leaf = _leaf(_ISSUE_660_KEY, 660, priority=Priority.P4)
    planner = DeepOrchestrate(configured_width=2)
    planner.register(leaf)

    first = plan_deep_orchestrate_refill(planner, _snapshot(), reserve_depth=1)
    fp = first["proposals"][0]["material_fingerprint"]
    sk = first["proposals"][0]["semantic_key"]

    # Second cycle: snapshot already has the candidate in the reserve
    second = plan_deep_orchestrate_refill(
        planner,
        _snapshot({"number": 660, "labels": ["oc-queued"], "material_fingerprint": fp, "semantic_key": sk}),
        reserve_depth=1,
    )

    assert second["proposals"] == [], second
    # reserve_satisfied or reserve_below_target_no_eligible_candidates
    assert "satisfied" in second["status"] or "no_eligible" in second["status"], second["status"]


def test_phase4_protected_production_leaf_fails_closed():
    """AUTH_PRODUCTION leaf never enters the reserve (auto-gated to OWNER_GATED).
    Proves: protected classification."""
    planner = DeepOrchestrate(configured_width=2)
    planner.register(_leaf("issue-999:retrieve-evidence", 999, authority_class=AUTH_PRODUCTION, priority=Priority.P0))

    result = plan_deep_orchestrate_refill(planner, _snapshot(), reserve_depth=1)

    assert result["proposals"] == []
    assert result["source_state_counts"].get("owner_gated", 0) == 1, result


def test_phase5_leaf_without_issue_lineage_is_rejected():
    """Leaf with no backing issue_number is rejected at the bridge (fail-closed on ambiguity).
    Proves: ambiguity does not fabricate requirements."""
    planner = DeepOrchestrate(configured_width=2)
    planner.register(TaskLeaf(
        key="speculative-future-feature:retrieve-evidence",
        title="Speculative work",
        repo="orchid-continuum-frontend",
        module="features/hypothetical",
        priority=Priority.P3,
        authority_class=AUTH_WORKSPACE,
        consequence_risk="low",
        issue_number=None,
    ))

    result = plan_deep_orchestrate_refill(planner, _snapshot(), reserve_depth=1)

    assert result["proposals"] == []
    assert result["source_rejections"] == [
        {"task_key": "speculative-future-feature:retrieve-evidence", "reason": "missing_issue_lineage"}
    ]


# ---------------------------------------------------------------------------
# Phase 6-10: Admission, reservation, execution, evidence, terminal state
# ---------------------------------------------------------------------------


def test_phase6_10_durable_reservation_execution_evidence_terminal(session, run_id):
    """Admit frontend #660, reserve in DurableOrchestrate (SQLite), execute via
    BoundedDispatcher + DeterministicResearchWorker, verify evidence + terminal state.
    Proves phases 6-10."""
    # 6. Admit — register into DurableOrchestrate
    res = DurableOrchestrate.create_run(session, run_id, configured_width=4)
    res.register(_leaf(_ISSUE_660_KEY, 660, priority=Priority.P4))
    assert res.get(_ISSUE_660_KEY).state == TaskState.READY

    # 7. Durable reservation proven by DB row
    row = session.query(DurableReservoirTask).filter(
        DurableReservoirTask.run_id == run_id,
        DurableReservoirTask.task_key == _ISSUE_660_KEY,
    ).first()
    assert row is not None, "Task not persisted to DB"
    assert row.state == TaskState.READY

    # 8. Execute via BoundedDispatcher + DeterministicResearchWorker
    worker = DeterministicResearchWorker()
    BoundedDispatcher(res, worker=worker).run(DispatchConfig(max_tasks=5, max_iterations=3))

    # 9. Evidence persisted
    completed_leaf = res.get(_ISSUE_660_KEY)
    assert completed_leaf.state == TaskState.COMPLETED
    assert completed_leaf.evidence is not None, "Evidence not persisted"
    evidence_output = completed_leaf.evidence.get("output", {})
    assert evidence_output.get("step") == "retrieve_evidence"
    assert not evidence_output.get("provider_api_called"), "Paid provider call detected"

    # 10. Terminal state — no orphaned LEASED or READY tasks
    all_rows = session.query(DurableReservoirTask).filter(
        DurableReservoirTask.run_id == run_id
    ).all()
    stuck = [r.task_key for r in all_rows if r.state in (TaskState.LEASED, TaskState.READY)]
    assert not stuck, f"Non-terminal tasks after completion: {stuck}"


# ---------------------------------------------------------------------------
# Phase 11-13: Post-completion reconciliation, depletion refill, idempotency
# ---------------------------------------------------------------------------


def test_phase11_13_post_completion_depletion_refill_idempotency(session, run_id):
    """Full depletion/refill/idempotency cycle.
    Phase 11: completed lineage not recreated.
    Phase 12: depletion triggers bounded deterministic refill from new work.
    Phase 13: second unchanged cycle creates zero new proposals."""

    # Execute #660 to completion
    res = DurableOrchestrate.create_run(session, run_id, configured_width=4)
    res.register(_leaf(_ISSUE_660_KEY, 660, priority=Priority.P4))
    BoundedDispatcher(res, worker=DeterministicResearchWorker()).run(
        DispatchConfig(max_tasks=5, max_iterations=3)
    )
    assert res.get(_ISSUE_660_KEY).state == TaskState.COMPLETED

    # --- Phase 11: post-completion reconciliation ---
    planner_post = DeepOrchestrate(configured_width=2)
    planner_post.register(_leaf(_ISSUE_660_KEY, 660, priority=Priority.P4, completed=True))

    result_post = plan_deep_orchestrate_refill(planner_post, _snapshot(), reserve_depth=2)

    assert result_post["proposals"] == [], (
        f"Completed lineage recreated: {result_post['proposals']}"
    )
    assert result_post["source_state_counts"].get("completed", 0) == 1

    # --- Phase 12: depletion triggers deterministic refill ---
    planner_refill = DeepOrchestrate(configured_width=4)
    planner_refill.register(_leaf(_ISSUE_660_KEY, 660, priority=Priority.P4, completed=True))
    planner_refill.register(_leaf(_ISSUE_1264_KEY, 1264, priority=Priority.P1))

    result_refill = plan_deep_orchestrate_refill(planner_refill, _snapshot(), reserve_depth=1)

    assert result_refill["status"] == "refill_planned", result_refill
    assert len(result_refill["proposals"]) == 1
    assert result_refill["proposals"][0]["source_ref"] == "#1264"
    assert result_refill["proposals"][0]["semantic_key"] == f"deep-orchestrate:{_ISSUE_1264_KEY}"

    fp_1264 = result_refill["proposals"][0]["material_fingerprint"]
    sk_1264 = result_refill["proposals"][0]["semantic_key"]

    # --- Phase 13: second unchanged cycle creates zero duplicates ---
    result_idempotent = plan_deep_orchestrate_refill(
        planner_refill,
        _snapshot({"number": 1264, "labels": ["oc-queued"], "material_fingerprint": fp_1264, "semantic_key": sk_1264}),
        reserve_depth=1,
    )

    assert result_idempotent["proposals"] == [], (
        f"Duplicate proposal on second unchanged cycle: {result_idempotent['proposals']}"
    )


# ---------------------------------------------------------------------------
# Phase 14: Zero paid provider calls — hard constraint
# ---------------------------------------------------------------------------


def test_phase14_zero_paid_provider_calls(session, run_id):
    """DeterministicResearchWorker executes admitted work with zero paid provider calls.
    Proves: NO-API constraint holds end-to-end."""
    res = DurableOrchestrate.create_run(session, run_id, configured_width=4)
    res.register(_leaf(_ISSUE_660_KEY, 660, priority=Priority.P4))
    res.register(_leaf(_ISSUE_1264_KEY, 1264, priority=Priority.P1))

    BoundedDispatcher(res, worker=DeterministicResearchWorker()).run(
        DispatchConfig(max_tasks=10, max_iterations=5)
    )

    paid_calls = 0
    for task in res.to_dict().get("tasks", {}).values():
        evidence = task.get("evidence") or {}
        if (evidence.get("output") or {}).get("provider_api_called"):
            paid_calls += 1

    assert paid_calls == 0, f"Paid provider calls: {paid_calls}"
    assert res.get(_ISSUE_660_KEY).state == TaskState.COMPLETED
    assert res.get(_ISSUE_1264_KEY).state == TaskState.COMPLETED


# ---------------------------------------------------------------------------
# Complete acceptance run summary — structured proof artifact
# ---------------------------------------------------------------------------


def test_queue_bridge_acceptance_run_1_summary():
    """Machine-readable proof summary. Records the acceptance run result for
    attestation in GitHub state. Fails if any invariant is violated."""
    proof: dict[str, Any] = {
        "proof_id": "oc-queue-bridge-acceptance-run-1",
        "schema": "oc.queue-bridge-acceptance.v1",
        "no_api_mode": True,
        "paid_provider_calls": 0,
        "invariants": {},
    }

    # --- Source discovery (Phase 1) ---
    planner = DeepOrchestrate(configured_width=4)
    planner.register(_leaf(_ISSUE_660_KEY, 660, priority=Priority.P4))
    discovery = plan_deep_orchestrate_refill(planner, _snapshot(), reserve_depth=1)
    proof["invariants"]["source_discovery"] = discovery["status"] == "refill_planned"
    proof["invariants"]["single_source_single_lineage"] = len(discovery["proposals"]) == 1

    fp = discovery["proposals"][0]["material_fingerprint"]
    sk = discovery["proposals"][0]["semantic_key"]

    # --- Duplicate suppression (Phase 3) ---
    dedup = plan_deep_orchestrate_refill(
        planner,
        _snapshot({"number": 660, "material_fingerprint": fp, "semantic_key": sk}),
        reserve_depth=1,
    )
    proof["invariants"]["unchanged_fingerprint_zero_proposals"] = dedup["proposals"] == []

    # --- Protected classification (Phase 4) ---
    protected_planner = DeepOrchestrate(configured_width=2)
    protected_planner.register(_leaf("issue-999:retrieve-evidence", 999, authority_class=AUTH_PRODUCTION))
    prot_result = plan_deep_orchestrate_refill(protected_planner, _snapshot(), reserve_depth=1)
    proof["invariants"]["protected_fails_closed"] = (
        prot_result["proposals"] == []
        and prot_result["source_state_counts"].get("owner_gated", 0) == 1
    )

    # --- Durable reservation + execution (Phases 6-10) ---
    e = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    _sqlite_create_all(e)
    factory = sessionmaker(bind=e, autocommit=False, autoflush=False)
    session = factory()
    run_id = f"qb-summary-{uuid.uuid4().hex[:8]}"

    res = DurableOrchestrate.create_run(session, run_id, configured_width=4)
    res.register(_leaf(_ISSUE_660_KEY, 660, priority=Priority.P4))
    res.register(_leaf(_ISSUE_1264_KEY, 1264, priority=Priority.P1))

    BoundedDispatcher(res, worker=DeterministicResearchWorker()).run(
        DispatchConfig(max_tasks=10, max_iterations=5)
    )

    all_tasks = res.to_dict().get("tasks", {})
    completed_count = sum(1 for t in all_tasks.values() if t.get("state") == TaskState.COMPLETED)
    stuck_count = sum(1 for t in all_tasks.values() if t.get("state") in (TaskState.LEASED, TaskState.READY))

    for t in all_tasks.values():
        evidence = t.get("evidence") or {}
        if (evidence.get("output") or {}).get("provider_api_called"):
            proof["paid_provider_calls"] += 1

    proof["invariants"]["all_tasks_completed"] = completed_count == 2
    proof["invariants"]["zero_orphaned_tasks"] = stuck_count == 0
    proof["invariants"]["zero_paid_provider_calls"] = proof["paid_provider_calls"] == 0
    proof["invariants"]["evidence_persisted"] = all(
        t.get("evidence") is not None for t in all_tasks.values()
    )

    # --- Post-completion reconciliation (Phase 11) ---
    planner_post = DeepOrchestrate(configured_width=4)
    for key, inum in ((_ISSUE_660_KEY, 660), (_ISSUE_1264_KEY, 1264)):
        planner_post.register(_leaf(key, inum, priority=Priority.P4, completed=True))
    post = plan_deep_orchestrate_refill(planner_post, _snapshot(), reserve_depth=2)
    proof["invariants"]["completed_lineage_not_recreated"] = post["proposals"] == []

    # --- Depletion refill (Phase 12) ---
    planner_refill = DeepOrchestrate(configured_width=4)
    for key, inum in ((_ISSUE_660_KEY, 660), (_ISSUE_1264_KEY, 1264)):
        planner_refill.register(_leaf(key, inum, priority=Priority.P4, completed=True))
    planner_refill.register(_leaf(_ISSUE_1085_KEY, 1085, priority=Priority.P1))

    refill = plan_deep_orchestrate_refill(planner_refill, _snapshot(), reserve_depth=1)
    proof["invariants"]["depletion_triggers_bounded_refill"] = (
        refill["status"] == "refill_planned" and len(refill["proposals"]) == 1
    )

    # --- Second unchanged cycle → zero duplicates (Phase 13) ---
    new_fp = refill["proposals"][0]["material_fingerprint"]
    new_sk = refill["proposals"][0]["semantic_key"]
    idempotent = plan_deep_orchestrate_refill(
        planner_refill,
        _snapshot({"number": 1085, "material_fingerprint": new_fp, "semantic_key": new_sk}),
        reserve_depth=1,
    )
    proof["invariants"]["second_unchanged_cycle_zero_duplicates"] = idempotent["proposals"] == []

    # --- Final assertion ---
    session.close()
    e.dispose()

    failing = [k for k, v in proof["invariants"].items() if not v]
    assert not failing, (
        f"Queue Bridge Acceptance Run #1 FAILED invariants: {failing}\nProof: {proof}"
    )
    assert proof["paid_provider_calls"] == 0
    assert proof["no_api_mode"] is True
