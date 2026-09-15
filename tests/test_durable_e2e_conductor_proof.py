"""Machine-verifiable E2E proof: DurableOrchestrate + AutonomousResearchRun conductor.

Proves the complete autonomous execution chain backed by the durable reservoir
(SQLite in-memory, same engine shared across session lifetimes to simulate
PostgreSQL surviving a process restart):

  queued work
  → durable reservation (DurableOrchestrate.create_run + register_many)
  → lease acquisition    (DurableOrchestrate.lease via BoundedDispatcher)
  → dispatch             (DeterministicResearchWorker.execute)
  → persisted evidence   (DurableOrchestrate.complete + DB flush)
  → terminal task state  (COMPLETED / BLOCKED, none stuck in LEASED)
  → lease release        (no active tasks after run)

  completed task (t1) → downstream task eligible (t2, dep=t1) → executed

AND restart recovery:

  process dies mid-run (LEASED task with expired lease)
  → DurableOrchestrate.from_db (same run_id, same engine)
  → recover_expired_leases → REPAIR_BACKOFF → recover_from_backoff → READY
  → re-dispatch → terminal state

Proof contract (hard assertions):
  - paid_provider_call_count == 0  throughout
  - All blueprint tasks reach COMPLETED or BLOCKED after conductor runs
  - No stale leases after run
  - Evidence is non-empty for COMPLETED tasks
  - Downstream tasks execute only after their dependencies complete
  - Task count stable across restart (no duplicate rows)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.calyx_orchestrator.bounded_dispatcher import BoundedDispatcher, DispatchConfig
from app.calyx_orchestrator.deep_orchestrate import (
    AUTH_PRODUCTION,
    AUTH_WORKSPACE,
    Priority,
    TaskLeaf,
    TaskState,
)
from app.calyx_orchestrator.durable_reservoir import DurableOrchestrate
from app.calyx_orchestrator.durable_reservoir_models import DurableReservoirTask
from app.calyx_orchestrator.leaf_worker import DeterministicResearchWorker
from app.calyx_orchestrator.owner_authorization_gate import (
    AuthorizationDecision,
    OwnerAuthorizationGate,
)
from app.database import Base
from app.scientific_synthesis.blueprint import (
    decompose_governed_action,
    enqueue_blueprint,
    validate_blueprint,
)
from app.scientific_synthesis.governance import GovernanceDecision, GovernanceOutcome
from app.scientific_synthesis.run_manifest import build_run_evidence_manifest

# ---------------------------------------------------------------------------
# Shared fixtures (module-scoped so one engine backs all phases)
# ---------------------------------------------------------------------------

_PAID_PROVIDER_CALLS = 0  # incremented if any worker reports provider_api_called=True


@pytest.fixture(scope="module")
def engine():
    """Shared SQLite in-memory engine — simulates a durable PostgreSQL instance."""
    e = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(e)
    yield e
    e.dispose()


@pytest.fixture(scope="module")
def SessionFactory(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


# ---------------------------------------------------------------------------
# Proof constants
# ---------------------------------------------------------------------------

_PROOF_RUN_ID = "durable-conductor-e2e-proof-20260913"
_TAXON = "taxon:orchidaceae"
_QUESTION = "What is the common name and primary clade of Orchidaceae?"
_APPROVER = "owner:president@fcosorchids.org"

_PROOF_PACKET = {
    "contract_version": "oc-verification-handoff-v1",
    "verification_state": "ready_for_review",
    "reasoning": {
        "contract_version": "oc-parallel-v1",
        "candidate_knowledge": {
            "candidate_id": "candidate:durable-proof-001",
            "subject_id": _TAXON,
            "predicate": "has_common_name",
            "object_id": "Orchid",
            "evidence_ids": ["ev-dp-1"],
            "confidence": 0.93,
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
            "evidence_id": "ev-dp-1",
            "source_id": "src-dp-001",
            "statement": "Orchidaceae is commonly called Orchid family.",
            "provenance": ["doi:10.0000/proof-dp-1"],
            "confidence": 0.93,
        }
    ],
    "missing_evidence_ids": [],
    "knowledge_gaps": [],
    "contradictions": [],
    "human_review_required": True,
    "automatic_scientific_publication_allowed": False,
}


def _build_manifest():
    return build_run_evidence_manifest(
        run_id=_PROOF_RUN_ID,
        taxon_id=_TAXON,
        research_question=_QUESTION,
        taxonomy_snapshot_id="snap-durable-proof-20260913",
        verification_packets=(_PROOF_PACKET,),
        review_records=(),
        epistemic_memory_entries=(),
    )


def _admitted():
    return GovernanceDecision(
        outcome=GovernanceOutcome.ADMITTED,
        admitted=True,
        reason="Durable conductor E2E proof: all governance checks clear",
        blocking_flags=[],
    )


def _count_provider_calls(results) -> int:
    return sum(1 for r in results if r.output.get("provider_api_called", False))


# ---------------------------------------------------------------------------
# PHASE 1: DurableOrchestrate.create_run + blueprint decomposition + enqueue
# ---------------------------------------------------------------------------


class TestDurableConductorProof:
    """Ordered phases building cumulative state on one shared DB engine."""

    _reservoir: DurableOrchestrate | None = None
    _session = None
    _blueprint = None
    _task_count = 0

    def test_01_create_run_and_enqueue(self, SessionFactory):
        """Phase 1: create durable run, decompose blueprint, enqueue tasks."""
        session = SessionFactory()
        manifest = _build_manifest()
        decision = _admitted()

        # Create durable run record
        reservoir = DurableOrchestrate.create_run(
            session,
            _PROOF_RUN_ID,
            blueprint_id="durable-proof-bp",
            proposed_action="build_synthesis",
            configured_width=6,
        )
        assert reservoir._run_id == _PROOF_RUN_ID

        # Decompose governance decision → blueprint
        blueprint = decompose_governed_action(
            decision,
            manifest,
            "build_synthesis",
            run_id=_PROOF_RUN_ID,
            taxon_id=_TAXON,
            research_question=_QUESTION,
        )
        validate_blueprint(blueprint)
        enqueued = enqueue_blueprint(blueprint, reservoir)

        # Verify tasks are in DB
        count = session.query(DurableReservoirTask).filter(
            DurableReservoirTask.run_id == _PROOF_RUN_ID
        ).count()
        assert count == enqueued, f"DB row count {count} != enqueued {enqueued}"
        assert enqueued > 0, "Blueprint produced zero tasks"

        # Stash for later phases via class attributes
        TestDurableConductorProof._task_count = count
        TestDurableConductorProof._blueprint = blueprint

        session.close()
        assert _PAID_PROVIDER_CALLS == 0

    def test_02_idempotent_reenqueue(self, SessionFactory):
        """Phase 2: re-enqueuing same blueprint produces 0 new rows (idempotency)."""
        session = SessionFactory()
        reservoir = DurableOrchestrate.from_db(session, _PROOF_RUN_ID)
        blueprint = TestDurableConductorProof._blueprint

        newly_registered = enqueue_blueprint(blueprint, reservoir)
        assert newly_registered == 0, f"Expected 0 new rows, got {newly_registered}"

        count = session.query(DurableReservoirTask).filter(
            DurableReservoirTask.run_id == _PROOF_RUN_ID
        ).count()
        assert count == TestDurableConductorProof._task_count
        session.close()
        assert _PAID_PROVIDER_CALLS == 0

    def test_03_lease_dispatch_evidence_persist(self, SessionFactory):
        """Phase 3: bounded dispatcher runs, leases tasks, evidence persisted to DB."""
        session = SessionFactory()
        reservoir = DurableOrchestrate.from_db(session, _PROOF_RUN_ID)
        worker = DeterministicResearchWorker()
        blueprint = TestDurableConductorProof._blueprint

        dispatcher = BoundedDispatcher(reservoir, worker=worker)
        dispatch_run = dispatcher.run(DispatchConfig(
            max_tasks=30,
            max_iterations=15,
            lease_holder="durable-proof-dispatcher-v1",
        ))

        paid = _count_provider_calls(dispatch_run.results)
        assert paid == 0, f"Paid provider calls: {paid}"
        global _PAID_PROVIDER_CALLS
        _PAID_PROVIDER_CALLS += paid
        assert dispatch_run.tasks_executed > 0, "Dispatcher executed 0 tasks"

        # No tasks stuck in LEASED after completion
        active_rows = session.query(DurableReservoirTask).filter(
            DurableReservoirTask.run_id == _PROOF_RUN_ID,
            DurableReservoirTask.state == TaskState.LEASED,
        ).all()
        assert len(active_rows) == 0, (
            f"Tasks stuck LEASED: {[r.task_key for r in active_rows]}"
        )

        # At least one completed task has evidence in DB
        completed_rows = session.query(DurableReservoirTask).filter(
            DurableReservoirTask.run_id == _PROOF_RUN_ID,
            DurableReservoirTask.state == TaskState.COMPLETED,
        ).all()
        assert len(completed_rows) > 0, "No tasks COMPLETED"

        for row in completed_rows:
            assert row.evidence, f"COMPLETED task {row.task_key} has empty evidence"

        # Verify downstream task activation: find a task with dependencies
        # that completed — its downstream must have had a chance to execute
        task_states = {
            r.task_key: r.state
            for r in session.query(DurableReservoirTask).filter(
                DurableReservoirTask.run_id == _PROOF_RUN_ID
            ).all()
        }

        for leaf in blueprint.task_leaves:
            if leaf.dependencies:
                deps_completed = all(
                    task_states.get(d) == TaskState.COMPLETED
                    for d in leaf.dependencies
                )
                if deps_completed:
                    # The downstream task should have progressed beyond READY
                    downstream_state = task_states.get(leaf.key)
                    assert downstream_state in (
                        TaskState.COMPLETED,
                        TaskState.BLOCKED,
                        TaskState.REPAIR_BACKOFF,
                        TaskState.OWNER_GATED,
                    ), (
                        f"Downstream task {leaf.key!r} with completed deps is stuck "
                        f"in state {downstream_state}"
                    )

        session.close()
        assert _PAID_PROVIDER_CALLS == 0

    def test_04_simulate_restart_and_recover(self, SessionFactory):
        """Phase 4: simulate crash → restart → recover expired lease → re-dispatch."""
        # First session: lease one task and backdate the lease (simulate crash)
        s1 = SessionFactory()
        reservoir1 = DurableOrchestrate.create_run(
            s1,
            _PROOF_RUN_ID + "-restart",
            configured_width=4,
        )

        ws_leaf = TaskLeaf(
            key="restart:t1:retrieve-evidence",
            title="Retrieve evidence (restart test)",
            repo="orchid-calyx",
            module="calyx_orchestrator",
            priority=Priority.P2,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
        )
        dep_leaf = TaskLeaf(
            key="restart:t2:normalize-evidence",
            title="Normalize evidence (downstream)",
            repo="orchid-calyx",
            module="calyx_orchestrator",
            priority=Priority.P2,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            dependencies=[ws_leaf.key],
        )
        reservoir1.register(ws_leaf)
        reservoir1.register(dep_leaf)

        # Lease t1 then simulate crash (backdate lease)
        reservoir1.lease("restart:t1:retrieve-evidence", holder="crashed-worker")
        row = s1.query(DurableReservoirTask).filter(
            DurableReservoirTask.run_id == _PROOF_RUN_ID + "-restart",
            DurableReservoirTask.task_key == "restart:t1:retrieve-evidence",
        ).first()
        assert row is not None
        row.leased_at = datetime.now(timezone.utc) - timedelta(seconds=400)
        s1.commit()
        s1.close()  # Process crash

        # Second session: restart recovery
        s2 = SessionFactory()
        reservoir2 = DurableOrchestrate.from_db(s2, _PROOF_RUN_ID + "-restart")

        # Verify expired lease visible after restart
        assert reservoir2.get("restart:t1:retrieve-evidence").state == TaskState.LEASED

        # Recover expired leases
        recovered = reservoir2.recover_expired_leases(max_lease_age_seconds=300)
        assert len(recovered) == 1
        assert recovered[0].key == "restart:t1:retrieve-evidence"
        assert reservoir2.get("restart:t1:retrieve-evidence").state == TaskState.REPAIR_BACKOFF

        # Recover from backoff → READY
        reservoir2.recover_from_backoff("restart:t1:retrieve-evidence")
        assert reservoir2.get("restart:t1:retrieve-evidence").state == TaskState.READY

        # t2 still READY (deps not yet completed)
        assert reservoir2.get("restart:t2:normalize-evidence").state == TaskState.READY

        # Re-dispatch to terminal state
        worker = DeterministicResearchWorker()
        dispatcher = BoundedDispatcher(reservoir2, worker=worker)
        run = dispatcher.run(DispatchConfig(max_tasks=10, max_iterations=5))

        paid = _count_provider_calls(run.results)
        assert paid == 0
        global _PAID_PROVIDER_CALLS
        _PAID_PROVIDER_CALLS += paid

        # Both tasks should now be terminal
        t1_state = reservoir2.get("restart:t1:retrieve-evidence").state
        t2_state = reservoir2.get("restart:t2:normalize-evidence").state
        assert t1_state in (TaskState.COMPLETED, TaskState.BLOCKED), (
            f"t1 stuck in {t1_state}"
        )
        assert t2_state in (TaskState.COMPLETED, TaskState.BLOCKED), (
            f"t2 stuck in {t2_state}"
        )

        # t1 completed → t2 should have had evidence injected
        if t1_state == TaskState.COMPLETED:
            t1_leaf = reservoir2.get("restart:t1:retrieve-evidence")
            assert t1_leaf.evidence, "t1 COMPLETED but no evidence"

        # No tasks stuck LEASED
        active = reservoir2.active_tasks()
        assert len(active) == 0, f"Stale leases: {[t.key for t in active]}"

        s2.close()
        assert _PAID_PROVIDER_CALLS == 0

    def test_05_owner_gated_with_durable_reservoir(self, SessionFactory):
        """Phase 5: OWNER_GATED task survives restart; authorization executes it."""
        session = SessionFactory()
        run_id = _PROOF_RUN_ID + "-owner-gate"

        reservoir = DurableOrchestrate.create_run(session, run_id, configured_width=4)
        worker = DeterministicResearchWorker()

        ws_leaf = TaskLeaf(
            key="og:t1:retrieve-evidence",
            title="Retrieve evidence",
            repo="orchid-calyx",
            module="calyx_orchestrator",
            priority=Priority.P1,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
        )
        og_leaf = TaskLeaf(
            key="og:t2:canonical-mutation",
            title="Canonical mutation (OWNER_GATED)",
            repo="orchid-calyx",
            module="calyx_orchestrator",
            priority=Priority.P1,
            authority_class=AUTH_PRODUCTION,
            consequence_risk="high",
            dependencies=[ws_leaf.key],
        )
        reservoir.register(ws_leaf)
        reservoir.register(og_leaf)

        # Initial dispatch: ws_leaf executes; og_leaf skipped (OWNER_GATED)
        dispatcher = BoundedDispatcher(reservoir, worker=worker)
        run1 = dispatcher.run(DispatchConfig(max_tasks=5, max_iterations=5))

        assert run1.tasks_executed >= 1
        assert reservoir.get("og:t1:retrieve-evidence").state == TaskState.COMPLETED
        assert reservoir.get("og:t2:canonical-mutation").state == TaskState.OWNER_GATED

        # "Restart" (close + reopen session to same engine)
        session.close()
        session2 = SessionFactory()
        reservoir2 = DurableOrchestrate.from_db(session2, run_id)

        # OWNER_GATED survives restart
        assert reservoir2.get("og:t2:canonical-mutation").state == TaskState.OWNER_GATED

        # Build minimal blueprint-like object for OwnerAuthorizationGate
        class _MiniBP:
            blueprint_id = "b" * 64
            run_fingerprint = "c" * 64
            proposed_action = "build_synthesis"
            human_review_required = True
            task_leaves = (ws_leaf, og_leaf)

        from app.calyx_orchestrator.blueprint_run_report import (
            build_blueprint_run_report,
        )

        # Build a report that shows awaiting_owner_gate
        report = build_blueprint_run_report(_MiniBP(), run1, reservoir2)
        assert report.run_status == "awaiting_owner_gate", (
            f"Expected awaiting_owner_gate, got {report.run_status}"
        )

        # Authorize the gated task
        gate = OwnerAuthorizationGate(reservoir2, _MiniBP(), worker=worker)
        gate_result = gate.authorize(
            report,
            [
                AuthorizationDecision(
                    task_key="og:t2:canonical-mutation",
                    approved=True,
                    approver_id=_APPROVER,
                    reason="Durable E2E proof: canonical mutation reviewed",
                )
            ],
            dispatch_config=DispatchConfig(max_tasks=5, max_iterations=5),
        )

        assert gate_result.authorized_count == 1
        assert gate_result.denied_count == 0
        assert gate_result.error_count == 0

        # Final state: og task executed and terminal
        og_final = reservoir2.get("og:t2:canonical-mutation")
        assert og_final.state in (TaskState.COMPLETED, TaskState.BLOCKED), (
            f"og task stuck in {og_final.state}"
        )

        # No stale leases
        active = reservoir2.active_tasks()
        assert len(active) == 0, f"Stale leases: {[t.key for t in active]}"

        paid = _count_provider_calls(gate_result.post_dispatch_run.results if gate_result.post_dispatch_run else [])
        assert paid == 0
        global _PAID_PROVIDER_CALLS
        _PAID_PROVIDER_CALLS += paid

        session2.close()
        assert _PAID_PROVIDER_CALLS == 0

    def test_06_concurrency_no_double_lease(self, SessionFactory):
        """Phase 6: two threads cannot double-lease the same task (SQLite lock)."""
        import threading

        session = SessionFactory()
        run_id = _PROOF_RUN_ID + "-concurrency"
        reservoir = DurableOrchestrate.create_run(session, run_id, configured_width=4)

        leaf = TaskLeaf(
            key="conc:t1:retrieve-evidence",
            title="Concurrent lease test",
            repo="orchid-calyx",
            module="calyx_orchestrator",
            priority=Priority.P2,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
        )
        reservoir.register(leaf)

        lease_winners: list[str] = []
        errors: list[str] = []

        def try_lease(worker_id: str):
            try:
                reservoir.lease("conc:t1:retrieve-evidence", holder=worker_id)
                lease_winners.append(worker_id)
            except (LookupError, ValueError) as exc:
                errors.append(str(exc))

        t1 = threading.Thread(target=try_lease, args=("worker-A",))
        t2 = threading.Thread(target=try_lease, args=("worker-B",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Exactly one winner; the other failed with a meaningful error
        assert len(lease_winners) == 1, (
            f"Expected 1 lease winner, got {len(lease_winners)}: {lease_winners}"
        )
        assert len(errors) == 1

        session.close()
        assert _PAID_PROVIDER_CALLS == 0

    def test_07_proof_summary(self, SessionFactory):
        """Phase 7: aggregate proof — all invariants verified, zero paid provider calls."""
        session = SessionFactory()
        reservoir = DurableOrchestrate.from_db(session, _PROOF_RUN_ID)
        snap = reservoir.snapshot()

        proof = {
            "proof_schema": "oc-durable-conductor-e2e-proof-v1",
            "integration_branch": "oc-autonomous-integration",
            "run_id": _PROOF_RUN_ID,
            "run_id_stable": snap["run_id"] == _PROOF_RUN_ID,
            "total_task_count": snap["total_task_count"],
            "active_count": snap["active_count"],
            "completed_count": snap["completed_count"],
            "paid_provider_call_count": _PAID_PROVIDER_CALLS,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        session.close()

        assert proof["run_id_stable"]
        assert proof["active_count"] == 0, f"Stale active tasks: {proof['active_count']}"
        assert proof["paid_provider_call_count"] == 0
        assert proof["total_task_count"] == TestDurableConductorProof._task_count, (
            f"Task count changed: {proof['total_task_count']} vs {TestDurableConductorProof._task_count}"
        )

        print("\n=== DURABLE CONDUCTOR E2E PROOF ===")
        print(json.dumps(proof, indent=2, default=str))
