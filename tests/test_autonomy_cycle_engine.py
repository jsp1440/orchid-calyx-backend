"""Adversarial and behavioural tests for the durable autonomy cycle engine.

The ten-cycle proof shows the loop works when nothing goes wrong. These tests
are the other half: they break the system on purpose, one failure mode at a
time, and assert that it fails safely and then keeps working.

Scenario coverage (mission adversarial matrix A-J):
    A  stale lease recovery
    B  duplicate lease attempt
    C  malformed work item
    D  worker interruption / process restart
    E  validation failure
    F  transient execution and provider-unavailable failure
    G  duplicate completion request
    H  queue-empty / replenishment
    I  mismatched or old autonomy context version
    J  partial state persisted before restart
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.calyx_orchestrator.deep_orchestrate import (
    AUTH_WORKSPACE,
    Priority,
    TaskLeaf,
    TaskState,
)
from runtime.autonomy_cycle_engine import (
    AutonomyCycleEngine,
    BrainDecisionEngine,
    ContextVersionError,
    Decision,
    DecisionRequest,
    EngineConfig,
    EngineJournal,
    ProviderIsolatedExecutor,
    ProviderUnavailable,
    StaticWorkSource,
    TransientExecutionError,
    load_canonical_context,
    normalize_work,
    validate_context,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def work(number: int, **overrides) -> dict:
    payload = {
        "number": number,
        "title": f"Autonomy work {number}",
        "repo": "orchid-continuum-frontend",
        "priority": int(Priority.P1),
    }
    payload.update(overrides)
    return payload


def make_engine(tmp_path: Path, backlog: list, *, run_id: str = "test-run", **kwargs):
    config = EngineConfig(
        run_id=run_id,
        db_url=f"sqlite:///{tmp_path / 'reservoir.db'}",
        journal_path=tmp_path / "journal.json",
        **kwargs,
    )
    return AutonomyCycleEngine(
        config,
        work_source=StaticWorkSource(backlog=list(backlog)),
        **({"executor": kwargs.pop("executor")} if "executor" in kwargs else {}),
    )


def leaf(key: str = "issue-1:retrieve-evidence", **kwargs) -> TaskLeaf:
    defaults = dict(
        title="t",
        repo="r",
        module="m",
        priority=Priority.P2,
        authority_class=AUTH_WORKSPACE,
        consequence_risk="low",
        issue_number=1,
        acceptance_criteria=["a"],
    )
    defaults.update(kwargs)
    return TaskLeaf(key=key, **defaults)


# ---------------------------------------------------------------------------
# Baseline: the happy path is genuinely durable
# ---------------------------------------------------------------------------


def test_ten_consecutive_cycles_complete_on_durable_storage(tmp_path):
    """Ten cycles, one durable reservoir, no manual intervention between them."""
    backlog = [work(9000 + i) for i in range(1, 11)]
    with make_engine(tmp_path, backlog) as engine:
        records = engine.run_cycles(10)

    assert len(records) == 10
    assert [r.status for r in records] == ["completed"] * 10
    assert [r.cycle for r in records] == list(range(1, 11))
    # Every cycle did distinct work.
    assert len({r.task_key for r in records}) == 10
    # Every cycle produced validated evidence and settled exactly once.
    for record in records:
        assert record.validation["passed"] is True
        assert record.settlement["settled"] is True
        assert record.settlement["duplicate_suppressed"] is False
        assert record.evidence["provider_api_called"] is False
        assert record.evidence["required_evidence_satisfied"] is True
        assert record.lease["granted"] is True


def test_journal_persists_cycles_across_engine_instances(tmp_path):
    """A second engine against the same storage continues the cycle count."""
    backlog = [work(100 + i) for i in range(1, 7)]
    with make_engine(tmp_path, backlog[:3]) as first:
        first_records = first.run_cycles(3)
    with make_engine(tmp_path, backlog[3:]) as second:
        second_records = second.run_cycles(3)

    assert [r.cycle for r in first_records] == [1, 2, 3]
    assert [r.cycle for r in second_records] == [4, 5, 6]
    assert all(r.status == "completed" for r in second_records)


# ---------------------------------------------------------------------------
# A. Stale lease recovery
# ---------------------------------------------------------------------------


def test_a_stale_lease_is_recovered_and_work_resumes(tmp_path):
    """A lease abandoned by a dead worker is reclaimed, not leaked forever."""
    with make_engine(tmp_path, [work(1)], lease_ttl_seconds=0.0) as engine:
        # Simulate a worker that leased the task and then died.
        engine.reservoir.register(leaf("issue-1:retrieve-evidence"))
        engine.reservoir.lease("issue-1:retrieve-evidence", holder="dead-worker")
        assert engine.reservoir.get("issue-1:retrieve-evidence").state == TaskState.LEASED

        record = engine.run_cycle()

        kinds = {entry["kind"] for entry in record.recovery}
        # Detected as abandoned, reclaimed from the dead holder, then re-run.
        assert "stale_lease_recovered" in kinds
        assert "backoff_recovered" in kinds
        assert record.status == "completed"
        assert record.task_key == "issue-1:retrieve-evidence"
        # The work is finished, and no longer attributed to the worker that died.
        recovered = engine.reservoir.get("issue-1:retrieve-evidence")
        assert recovered.state == TaskState.COMPLETED
        assert recovered.lease_holder == engine.config.lease_holder


def test_a_stale_lease_recovery_leaves_fresh_leases_alone(tmp_path):
    """Recovery must not steal a lease that is still within its TTL."""
    with make_engine(tmp_path, [], lease_ttl_seconds=3600.0) as engine:
        engine.reservoir.register(leaf("issue-7:retrieve-evidence"))
        engine.reservoir.lease("issue-7:retrieve-evidence", holder="live-worker")
        expired = engine.reservoir.recover_expired_leases(3600.0)
        assert expired == []
        assert engine.reservoir.get("issue-7:retrieve-evidence").lease_holder == "live-worker"


# ---------------------------------------------------------------------------
# B. Duplicate lease attempt
# ---------------------------------------------------------------------------


def test_b_duplicate_lease_attempt_is_refused(tmp_path):
    """Two holders cannot own the same task at once."""
    with make_engine(tmp_path, []) as engine:
        engine.reservoir.register(leaf("issue-2:retrieve-evidence"))
        engine.reservoir.lease("issue-2:retrieve-evidence", holder="worker-a")

        with pytest.raises(ValueError, match="TASK_NOT_READY"):
            engine.reservoir.lease("issue-2:retrieve-evidence", holder="worker-b")

        # Ownership is unchanged by the failed attempt.
        assert engine.reservoir.get("issue-2:retrieve-evidence").lease_holder == "worker-a"


def test_b_concurrent_workers_cannot_both_win_the_same_lease(tmp_path):
    """Regression: eight racing workers, one winner, every time.

    Before the lease acquired its task under a conditional UPDATE, each
    DurableOrchestrate instance relied on a per-instance ``threading.Lock``
    that competing instances never contend on. Two workers could both read the
    task as READY and both come away believing they held it -- and then both
    execute the same work. This reproduces that race directly, at thread level
    rather than by inspecting only the final row.
    """
    import threading

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.calyx_orchestrator.durable_reservoir import DurableOrchestrate
    from app.calyx_orchestrator.durable_reservoir_models import (
        DurableReservoirRun,
        DurableReservoirTask,
    )

    engine = create_engine(
        f"sqlite:///{tmp_path / 'race.db'}", connect_args={"check_same_thread": False}
    )
    # Only the reservoir tables: create_all() on the shared base would pull in
    # every model other test modules have registered, some of them qualified
    # into PostgreSQL schemas SQLite cannot create.
    for model in (DurableReservoirRun, DurableReservoirTask):
        model.__table__.create(bind=engine, checkfirst=True)
    session_factory = sessionmaker(bind=engine)

    workers = 8
    trials = 5
    for trial in range(trials):
        run_id = f"race-{trial}"
        setup = session_factory()
        reservoir = DurableOrchestrate.create_run(setup, run_id, configured_width=8)
        reservoir.register(leaf("t:contested"))
        setup.close()

        barrier = threading.Barrier(workers)
        outcomes: list[str] = []
        guard = threading.Lock()

        def contend() -> None:
            session = session_factory()
            local = DurableOrchestrate.from_db(session, run_id)
            barrier.wait()
            try:
                local.lease("t:contested", holder=f"worker-{threading.get_ident()}")
                result = "won"
            except (ValueError, LookupError):
                result = "lost"
            except Exception as exc:  # must never surface an unhandled fault
                result = f"error:{type(exc).__name__}"
            finally:
                session.close()
            with guard:
                outcomes.append(result)

        threads = [threading.Thread(target=contend) for _ in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not [o for o in outcomes if o.startswith("error")], outcomes
        assert outcomes.count("won") == 1, (
            f"trial {trial}: {outcomes.count('won')} workers believed they held "
            f"the same lease; exactly one may win"
        )
        assert outcomes.count("lost") == workers - 1

    engine.dispose()


def test_b_engine_cycle_reports_lease_failure_without_crashing(tmp_path):
    """A lease lost between decision and acquisition ends the cycle safely."""

    class StealingDecision:
        name = "stealing-decision"

        def __init__(self, reservoir):
            self.reservoir = reservoir

        def decide(self, request: DecisionRequest) -> Decision:
            key = "issue-3:retrieve-evidence"
            # Another worker grabs the task after it was chosen.
            self.reservoir.lease(key, holder="racing-worker")
            return Decision(
                selected_key=key,
                action="execute",
                rationale="race",
                ranking=((key, 1.0),),
                deferred=(),
                escalated=(),
                decider=self.name,
            )

    config = EngineConfig(
        run_id="race",
        db_url=f"sqlite:///{tmp_path / 'r.db'}",
        journal_path=tmp_path / "j.json",
    )
    engine = AutonomyCycleEngine(
        config,
        work_source=StaticWorkSource(backlog=[work(3)]),
        decision_engine=None,
    )
    engine.decision_engine = StealingDecision(engine.reservoir)
    try:
        record = engine.run_cycle()
    finally:
        engine.close()

    assert record.status == "lease-failed"
    assert record.lease["granted"] is False
    assert "TASK_NOT_READY" in record.failure_reason


# ---------------------------------------------------------------------------
# C. Malformed work item
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload,expected",
    [
        ("not-a-dict", "not_a_mapping"),
        ({"number": "twelve"}, "issue_number_not_int"),
        ({"number": -4}, "issue_number_not_positive"),
        ({"number": 0}, "issue_number_not_positive"),
        ({"number": True}, "issue_number_not_int"),
        ({"number": 1, "title": 12}, "title_not_string"),
        ({"number": 1, "repo": ""}, "repo_invalid"),
        ({"number": 1, "priority": "high"}, "priority_not_int"),
        ({"number": 1, "priority": 99}, "priority_out_of_range"),
        ({"number": 1, "step": "  "}, "step_invalid"),
    ],
)
def test_c_malformed_work_is_rejected_with_a_specific_reason(payload, expected):
    with pytest.raises(ValueError, match=expected):
        normalize_work(payload)


def test_c_malformed_work_does_not_stop_the_cycle(tmp_path):
    """Bad payloads are rejected; good work in the same batch still runs."""

    class MixedSource:
        name = "mixed"

        def __init__(self):
            self.calls = 0

        def discover(self, cycle):
            self.calls += 1
            if self.calls == 1:
                return ["garbage", {"number": -1}, work(42)]
            return []

    config = EngineConfig(
        run_id="malformed",
        db_url=f"sqlite:///{tmp_path / 'r.db'}",
        journal_path=tmp_path / "j.json",
    )
    with AutonomyCycleEngine(config, work_source=MixedSource()) as engine:
        record = engine.run_cycle()

    assert record.status == "completed"
    assert record.task_key == "issue-42:retrieve-evidence"
    assert record.admission["rejected"] == 2
    assert record.admission["admitted"] == 1
    reasons = " ".join(entry["reason"] for entry in record.rejected)
    assert "not_a_mapping" in reasons
    assert "issue_number_not_positive" in reasons


def test_c_a_work_source_that_raises_does_not_kill_the_loop(tmp_path):
    class BrokenSource:
        name = "broken"

        def discover(self, cycle):
            raise RuntimeError("upstream exploded")

    config = EngineConfig(
        run_id="broken-source",
        db_url=f"sqlite:///{tmp_path / 'r.db'}",
        journal_path=tmp_path / "j.json",
    )
    with AutonomyCycleEngine(config, work_source=BrokenSource()) as engine:
        record = engine.run_cycle()

    assert record.status == "no-work"
    assert "upstream exploded" in record.admission["source_error"]


# ---------------------------------------------------------------------------
# D. Worker interruption / restart
# ---------------------------------------------------------------------------


def test_d_interrupted_work_is_recovered_by_a_restarted_engine(tmp_path):
    """Kill a worker mid-flight; a fresh process reclaims and finishes the work."""
    db_url = f"sqlite:///{tmp_path / 'r.db'}"
    journal = tmp_path / "j.json"

    # First process: lease the task, then "crash" before settling it.
    first = AutonomyCycleEngine(
        EngineConfig(run_id="restart", db_url=db_url, journal_path=journal),
        work_source=StaticWorkSource(backlog=[work(55)]),
    )
    first.reservoir.register(leaf("issue-55:retrieve-evidence", issue_number=55))
    first.reservoir.lease("issue-55:retrieve-evidence", holder="crashed-worker")
    first.reservoir.advance("issue-55:retrieve-evidence", state=TaskState.RUNNING)
    first._session.close()  # abrupt termination: no settle, no journal flush
    first._engine.dispose()

    # Second process: same storage, zero lease tolerance so the stale lease is seen.
    second = AutonomyCycleEngine(
        EngineConfig(
            run_id="restart",
            db_url=db_url,
            journal_path=journal,
            lease_ttl_seconds=0.0,
        ),
        work_source=StaticWorkSource(backlog=[]),
    )
    try:
        recovery_cycle = second.run_cycle()
        # The interrupted task was reclaimed from the dead holder...
        assert any(
            entry["kind"] == "stale_lease_recovered"
            and entry["task_key"] == "issue-55:retrieve-evidence"
            for entry in recovery_cycle.recovery
        )
        # ...and the same cycle carries it through to completion. No human
        # touched anything between the crash and the finished work.
        assert recovery_cycle.status == "completed"
        assert recovery_cycle.task_key == "issue-55:retrieve-evidence"
        assert (
            second.reservoir.get("issue-55:retrieve-evidence").state
            == TaskState.COMPLETED
        )
        # The restarted process picked up the cycle count from durable state.
        assert recovery_cycle.cycle == 1
        assert recovery_cycle.admission["discovered"] == 0
    finally:
        second.close()


# ---------------------------------------------------------------------------
# E. Validation failure
# ---------------------------------------------------------------------------


def test_e_validation_failure_blocks_completion_and_records_the_reason(tmp_path):
    """Work that executes but produces no valid evidence is never marked done."""

    class EmptyOutputWorker:
        def execute(self, task_leaf):
            from app.calyx_orchestrator.leaf_worker import TaskExecutionResult

            return TaskExecutionResult(
                task_key=task_leaf.key,
                worker_id="empty-worker",
                status="completed",
                started_at="2026-09-21T00:00:00+00:00",
                completed_at="2026-09-21T00:00:01+00:00",
                duration_seconds=1.0,
                output={},  # no evidence at all
            )

    config = EngineConfig(
        run_id="validation",
        db_url=f"sqlite:///{tmp_path / 'r.db'}",
        journal_path=tmp_path / "j.json",
    )
    with AutonomyCycleEngine(
        config,
        work_source=StaticWorkSource(backlog=[work(61)]),
        executor=EmptyOutputWorker(),
    ) as engine:
        record = engine.run_cycle()

        assert record.status == "validation-failed"
        assert record.validation["passed"] is False
        assert "output_present" in record.failure_reason
        # The task is emphatically not completed.
        assert (
            engine.reservoir.get("issue-61:retrieve-evidence").state
            == TaskState.REPAIR_BACKOFF
        )
        # The failure is remembered for the decision layer.
        assert engine.journal.failure_memory["issue-61:retrieve-evidence"] == 1


def test_e_provider_call_in_a_no_api_run_fails_validation(tmp_path):
    """A worker that reaches a paid provider cannot pass validation."""

    class ProviderCallingWorker:
        def execute(self, task_leaf):
            from app.calyx_orchestrator.leaf_worker import TaskExecutionResult

            return TaskExecutionResult(
                task_key=task_leaf.key,
                worker_id="provider-worker",
                status="completed",
                started_at="2026-09-21T00:00:00+00:00",
                completed_at="2026-09-21T00:00:01+00:00",
                duration_seconds=1.0,
                output={"step": "x", "provider_api_called": True},
            )

    config = EngineConfig(
        run_id="provider-guard",
        db_url=f"sqlite:///{tmp_path / 'r.db'}",
        journal_path=tmp_path / "j.json",
    )
    with AutonomyCycleEngine(
        config,
        work_source=StaticWorkSource(backlog=[work(62)]),
        executor=ProviderCallingWorker(),
    ) as engine:
        record = engine.run_cycle()

    assert record.status == "validation-failed"
    assert "no_unauthorized_provider_call" in record.failure_reason


# ---------------------------------------------------------------------------
# F. Transient and provider failures
# ---------------------------------------------------------------------------


def test_f_transient_error_is_retried_within_the_cycle_and_succeeds(tmp_path):
    """Two transient faults, then success -- one cycle, no human involved."""
    executor = ProviderIsolatedExecutor(
        failure_plan={
            "issue-70:retrieve-evidence": [
                TransientExecutionError("connection reset"),
                TransientExecutionError("read timeout"),
            ]
        }
    )
    config = EngineConfig(
        run_id="transient",
        db_url=f"sqlite:///{tmp_path / 'r.db'}",
        journal_path=tmp_path / "j.json",
        max_execution_attempts=3,
    )
    with AutonomyCycleEngine(
        config,
        work_source=StaticWorkSource(backlog=[work(70)]),
        executor=executor,
    ) as engine:
        record = engine.run_cycle()

    assert record.status == "completed"
    assert record.execution["attempts"] == 3
    retries = [e for e in record.recovery if e["kind"] == "transient_error_retried"]
    assert len(retries) == 2


def test_f_retry_exhaustion_defers_safely(tmp_path):
    """Endless transient faults exhaust the bound and defer -- they do not spin."""
    executor = ProviderIsolatedExecutor(
        failure_plan={
            "issue-71:retrieve-evidence": [TransientExecutionError("down")] * 10
        }
    )
    config = EngineConfig(
        run_id="exhausted",
        db_url=f"sqlite:///{tmp_path / 'r.db'}",
        journal_path=tmp_path / "j.json",
        max_execution_attempts=3,
    )
    with AutonomyCycleEngine(
        config,
        work_source=StaticWorkSource(backlog=[work(71)]),
        executor=executor,
    ) as engine:
        record = engine.run_cycle()
        assert record.status == "deferred"
        assert record.execution["classification"] == "retry_exhausted"
        assert record.execution["attempts"] == 3
        assert (
            engine.reservoir.get("issue-71:retrieve-evidence").state
            == TaskState.REPAIR_BACKOFF
        )


def test_f_provider_unavailable_defers_work_without_breaking_orchestration(tmp_path):
    """The core keeps running when a paid provider lane is unreachable."""
    executor = ProviderIsolatedExecutor(
        failure_plan={"issue-72:retrieve-evidence": [ProviderUnavailable("no credit")]}
    )
    config = EngineConfig(
        run_id="provider-down",
        db_url=f"sqlite:///{tmp_path / 'r.db'}",
        journal_path=tmp_path / "j.json",
    )
    with AutonomyCycleEngine(
        config,
        work_source=StaticWorkSource(backlog=[work(72), work(73)]),
        executor=executor,
    ) as engine:
        first = engine.run_cycle()
        assert first.status == "deferred"
        assert first.execution["classification"] == "provider_unavailable"
        assert any(
            e["kind"] == "provider_unavailable_deferred" for e in first.recovery
        )

        # Decisive point: the orchestration loop is still alive and still works.
        second = engine.run_cycle()
        assert second.status == "completed"
        assert second.execution["classification"] == "executed"


def test_f_retry_exhausted_work_is_held_not_retried_forever(tmp_path):
    """Once the attempt budget is spent, reconciliation stops re-admitting it."""
    key = "issue-74:retrieve-evidence"
    executor = ProviderIsolatedExecutor(
        failure_plan={key: [TransientExecutionError("always")] * 50}
    )
    config = EngineConfig(
        run_id="held",
        db_url=f"sqlite:///{tmp_path / 'r.db'}",
        journal_path=tmp_path / "j.json",
        max_execution_attempts=1,
    )
    with AutonomyCycleEngine(
        config,
        work_source=StaticWorkSource(backlog=[work(74)]),
        executor=executor,
    ) as engine:
        engine.run_cycle()
        engine.journal.failure_memory[key] = 99  # budget definitively spent
        second = engine.run_cycle()

    assert any(e["kind"] == "retry_exhausted_held" for e in second.recovery)


# ---------------------------------------------------------------------------
# G. Duplicate completion
# ---------------------------------------------------------------------------


def test_g_duplicate_completion_is_suppressed_and_evidence_is_preserved(tmp_path):
    """A replayed completion cannot rewrite the record of settled work."""
    with make_engine(tmp_path, [work(80)]) as engine:
        record = engine.run_cycle()
        assert record.settlement["settled"] is True
        key = record.task_key
        original = dict(engine.reservoir.get(key).evidence)

        replay = engine.reservoir.settle(
            key,
            evidence={"worker_id": "impostor", "status": "tampered"},
            require_lease=True,
            holder=engine.config.lease_holder,
        )

        assert replay.settled is False
        assert replay.duplicate is True
        assert engine.reservoir.get(key).evidence == original


def test_g_completion_without_a_lease_is_refused(tmp_path):
    """Completion is an ownership-bearing act, not a free-for-all."""
    with make_engine(tmp_path, []) as engine:
        engine.reservoir.register(leaf("issue-81:retrieve-evidence", issue_number=81))
        with pytest.raises(PermissionError, match="COMPLETION_WITHOUT_LEASE"):
            engine.reservoir.settle(
                "issue-81:retrieve-evidence", evidence={"x": 1}, require_lease=True
            )
        assert engine.reservoir.get("issue-81:retrieve-evidence").state == TaskState.READY


def test_g_completion_by_a_non_holder_is_refused(tmp_path):
    with make_engine(tmp_path, []) as engine:
        engine.reservoir.register(leaf("issue-82:retrieve-evidence", issue_number=82))
        engine.reservoir.lease("issue-82:retrieve-evidence", holder="rightful")
        with pytest.raises(PermissionError, match="COMPLETION_BY_NON_HOLDER"):
            engine.reservoir.settle(
                "issue-82:retrieve-evidence",
                evidence={"x": 1},
                require_lease=True,
                holder="impostor",
            )


# ---------------------------------------------------------------------------
# H. Queue empty / replenishment
# ---------------------------------------------------------------------------


def test_h_empty_queue_reports_starvation_rather_than_failing(tmp_path):
    """No work is a state to report, not a crash and not a fake success."""
    with make_engine(tmp_path, []) as engine:
        record = engine.run_cycle()

    assert record.status == "no-work"
    assert record.decision["action"] == "await-replenishment"
    assert record.decision["selected_key"] is None
    assert record.replenishment["starved"] is True


def test_h_replenishment_resumes_work_after_starvation(tmp_path):
    """A starved loop picks work back up as soon as the source refills."""

    class LateSource:
        name = "late"

        def __init__(self):
            self.cycle_seen = 0

        def discover(self, cycle):
            self.cycle_seen = cycle
            return [work(90)] if cycle >= 3 else []

    config = EngineConfig(
        run_id="starve",
        db_url=f"sqlite:///{tmp_path / 'r.db'}",
        journal_path=tmp_path / "j.json",
    )
    with AutonomyCycleEngine(config, work_source=LateSource()) as engine:
        records = engine.run_cycles(4, stop_on_failure=False)

    assert [r.status for r in records[:2]] == ["no-work", "no-work"]
    assert records[2].status == "completed"
    assert records[2].task_key == "issue-90:retrieve-evidence"


def test_h_replenishment_reports_next_available_work(tmp_path):
    """The cycle record states what is queued next, not just what it did."""
    config = EngineConfig(
        run_id="replenish",
        db_url=f"sqlite:///{tmp_path / 'r.db'}",
        journal_path=tmp_path / "j.json",
        max_admissions_per_cycle=4,
    )

    class BatchSource:
        name = "batch"

        def __init__(self):
            self.done = False

        def discover(self, cycle):
            if self.done:
                return []
            self.done = True
            return [work(200), work(201), work(202)]

    with AutonomyCycleEngine(config, work_source=BatchSource()) as engine:
        first = engine.run_cycle()

    assert first.status == "completed"
    assert first.admission["admitted"] == 3
    # Two remain queued for the following cycles.
    assert first.replenishment["ready_next"] == 2
    assert first.replenishment["starved"] is False


# ---------------------------------------------------------------------------
# I. Context version mismatch
# ---------------------------------------------------------------------------


def test_i_canonical_context_on_disk_is_valid():
    context = load_canonical_context()
    assert context["schema"] == "oc.autonomy-context.v1"
    assert context["version"] == "1.0.0"
    assert context["evaluation"]["autonomy_proof_target"] == 10


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ({"schema": "oc.autonomy-context.v2"}, "CONTEXT_SCHEMA_UNSUPPORTED"),
        ({"version": "2.0.0"}, "CONTEXT_VERSION_UNSUPPORTED"),
        ({"version": "0.9.0"}, "CONTEXT_VERSION_UNSUPPORTED"),
        ({"version": ""}, "CONTEXT_VERSION_INVALID"),
        ({"version": "not-a-version"}, "CONTEXT_VERSION_INVALID"),
        ({"provider_neutral": False}, "CONTEXT_NOT_PROVIDER_NEUTRAL"),
        ({"required_evidence": []}, "CONTEXT_MISSING_REQUIRED_EVIDENCE"),
    ],
)
def test_i_incompatible_context_is_refused(mutation, expected):
    context = load_canonical_context()
    context.update(mutation)
    with pytest.raises(ContextVersionError, match=expected):
        validate_context(context)


def test_i_engine_refuses_to_start_under_an_incompatible_context(tmp_path):
    """Fail closed at construction: never run a loop under rules you do not know."""
    context = load_canonical_context()
    context["version"] = "2.0.0"
    config = EngineConfig(
        run_id="bad-context",
        db_url=f"sqlite:///{tmp_path / 'r.db'}",
        journal_path=tmp_path / "j.json",
    )
    with pytest.raises(ContextVersionError, match="CONTEXT_VERSION_UNSUPPORTED"):
        AutonomyCycleEngine(
            config, work_source=StaticWorkSource(backlog=[]), context=context
        )


def test_i_context_missing_completion_evidence_rule_is_refused():
    context = load_canonical_context()
    context["operating_rules"] = dict(context["operating_rules"])
    context["operating_rules"]["require_evidence_for_completion"] = False
    with pytest.raises(ContextVersionError, match="CONTEXT_MUST_REQUIRE_COMPLETION_EVIDENCE"):
        validate_context(context)


# ---------------------------------------------------------------------------
# J. Partial / corrupt persisted state
# ---------------------------------------------------------------------------


def test_j_corrupt_journal_is_recovered_rather_than_fatal(tmp_path):
    """A damaged journal degrades to lost history, never to a dead system."""
    journal_path = tmp_path / "journal.json"
    journal_path.write_text("{ this is not json at all", encoding="utf-8")

    with make_engine(tmp_path, [work(95)]) as engine:
        assert engine.journal.recovered_from_corruption is True
        record = engine.run_cycle()

    assert record.status == "completed"
    assert any(e["kind"] == "journal_recovered" for e in record.recovery)


def test_j_truncated_journal_is_recovered(tmp_path):
    """Half a file written before a crash is still recoverable."""
    journal_path = tmp_path / "journal.json"
    journal_path.write_text('{"schema": "oc.autonomy-cycle-jour', encoding="utf-8")
    journal = EngineJournal.load(journal_path)
    assert journal.recovered_from_corruption is True
    assert journal.cycles == []


def test_j_journal_with_wrong_types_discards_only_bad_fields(tmp_path):
    """Partial corruption loses the damaged field, not the whole journal."""
    journal_path = tmp_path / "journal.json"
    journal_path.write_text(
        json.dumps(
            {
                "schema": "oc.autonomy-cycle-journal.v1",
                "admitted_fingerprints": {"issue-1:x": "abc"},
                "failure_memory": "this should be a mapping",
                "cycles": [{"cycle": 1, "status": "completed"}],
            }
        ),
        encoding="utf-8",
    )
    journal = EngineJournal.load(journal_path)

    assert journal.recovered_from_corruption is True
    assert "failure_memory" in journal.corruption_detail
    # The intact fields survived.
    assert journal.admitted_fingerprints == {"issue-1:x": "abc"}
    assert len(journal.cycles) == 1
    assert journal.failure_memory == {}


def test_j_journal_from_a_foreign_schema_is_not_trusted(tmp_path):
    journal_path = tmp_path / "journal.json"
    journal_path.write_text(
        json.dumps({"schema": "something.else.v9", "cycles": [{"cycle": 1}]}),
        encoding="utf-8",
    )
    journal = EngineJournal.load(journal_path)
    assert journal.recovered_from_corruption is True
    assert journal.cycles == []


def test_j_journal_save_is_atomic(tmp_path):
    """The replacing write must never be able to destroy the existing journal."""
    journal_path = tmp_path / "journal.json"
    journal = EngineJournal(path=journal_path)
    journal.cycles = [{"cycle": 1, "status": "completed"}]
    journal.save()

    reloaded = EngineJournal.load(journal_path)
    assert reloaded.cycles == [{"cycle": 1, "status": "completed"}]
    assert reloaded.recovered_from_corruption is False
    # No temporary files were left lying around.
    assert [p.name for p in tmp_path.iterdir()] == ["journal.json"]


def test_j_reservoir_state_survives_an_engine_that_never_closed(tmp_path):
    """Durability comes from the store, not from an orderly shutdown."""
    db_url = f"sqlite:///{tmp_path / 'r.db'}"
    first = AutonomyCycleEngine(
        EngineConfig(run_id="nofinish", db_url=db_url, journal_path=tmp_path / "j.json"),
        work_source=StaticWorkSource(backlog=[work(96)]),
    )
    record = first.run_cycle()
    assert record.status == "completed"
    # No close(): simulate the process simply going away.
    del first

    second = AutonomyCycleEngine(
        EngineConfig(run_id="nofinish", db_url=db_url, journal_path=tmp_path / "j.json"),
        work_source=StaticWorkSource(backlog=[]),
    )
    try:
        task = second.reservoir.get("issue-96:retrieve-evidence")
        assert task is not None
        assert task.state == TaskState.COMPLETED
    finally:
        second.close()


# ---------------------------------------------------------------------------
# Decision layer: the Brain must actually decide
# ---------------------------------------------------------------------------


def test_brain_prefers_higher_priority_work():
    brain = BrainDecisionEngine()
    candidates = (
        leaf("issue-1:retrieve-evidence", priority=Priority.P3, issue_number=1),
        leaf("issue-2:retrieve-evidence", priority=Priority.P0, issue_number=2),
        leaf("issue-3:retrieve-evidence", priority=Priority.P2, issue_number=3),
    )
    decision = brain.decide(
        DecisionRequest(
            cycle=1,
            candidates=candidates,
            failure_memory={},
            completed_keys=frozenset(),
            queue_depth=3,
            active_leases=0,
            context={},
        )
    )
    assert decision.selected_key == "issue-2:retrieve-evidence"
    assert decision.action == "execute"
    assert set(decision.deferred) == {
        "issue-1:retrieve-evidence",
        "issue-3:retrieve-evidence",
    }


def test_brain_learns_from_recorded_failures_and_reorders():
    """Evidence from earlier cycles must change later decisions, not just log."""
    brain = BrainDecisionEngine()
    candidates = (
        leaf("issue-1:retrieve-evidence", priority=Priority.P0, issue_number=1),
        leaf("issue-2:retrieve-evidence", priority=Priority.P2, issue_number=2),
    )
    base = DecisionRequest(
        cycle=1,
        candidates=candidates,
        failure_memory={},
        completed_keys=frozenset(),
        queue_depth=2,
        active_leases=0,
        context={},
    )
    assert brain.decide(base).selected_key == "issue-1:retrieve-evidence"

    # The same queue, after the top-priority task has failed twice.
    informed = DecisionRequest(
        cycle=2,
        candidates=candidates,
        failure_memory={"issue-1:retrieve-evidence": 2},
        completed_keys=frozenset(),
        queue_depth=2,
        active_leases=0,
        context={},
    )
    decision = brain.decide(informed)
    assert decision.selected_key == "issue-2:retrieve-evidence"
    assert "Prior recorded failures for this task: 0" in decision.rationale


def test_brain_escalates_high_consequence_work_instead_of_executing_it():
    brain = BrainDecisionEngine()
    candidates = (
        leaf(
            "issue-1:retrieve-evidence",
            priority=Priority.P0,
            issue_number=1,
            consequence_risk="high",
        ),
    )
    decision = brain.decide(
        DecisionRequest(
            cycle=1,
            candidates=candidates,
            failure_memory={},
            completed_keys=frozenset(),
            queue_depth=1,
            active_leases=0,
            context={},
        )
    )
    assert decision.selected_key is None
    assert decision.action == "escalate-owner-gate"
    assert decision.escalated == ("issue-1:retrieve-evidence",)


def test_brain_decision_is_deterministic():
    """Same state, same decision -- otherwise a proof run is not reproducible."""
    brain = BrainDecisionEngine()
    candidates = tuple(
        leaf(f"issue-{n}:retrieve-evidence", priority=Priority.P1, issue_number=n)
        for n in range(1, 6)
    )
    request = DecisionRequest(
        cycle=1,
        candidates=candidates,
        failure_memory={},
        completed_keys=frozenset(),
        queue_depth=5,
        active_leases=0,
        context={},
    )
    first = brain.decide(request)
    second = brain.decide(request)
    assert first.selected_key == second.selected_key
    assert first.ranking == second.ranking


def test_brain_selection_actually_drives_execution(tmp_path):
    """Proof the decision layer is load-bearing, not decorative."""

    class PickLast:
        name = "pick-last"

        def decide(self, request: DecisionRequest) -> Decision:
            keys = sorted(c.key for c in request.candidates)
            chosen = keys[-1] if keys else None
            return Decision(
                selected_key=chosen,
                action="execute" if chosen else "await-replenishment",
                rationale="deliberately picks the last key",
                ranking=((chosen, 0.0),) if chosen else (),
                deferred=tuple(keys[:-1]),
                escalated=(),
                decider=self.name,
            )

    config = EngineConfig(
        run_id="decider",
        db_url=f"sqlite:///{tmp_path / 'r.db'}",
        journal_path=tmp_path / "j.json",
        max_admissions_per_cycle=4,
    )

    class Batch:
        name = "batch"

        def __init__(self):
            self.done = False

        def discover(self, cycle):
            if self.done:
                return []
            self.done = True
            return [work(301), work(302), work(303)]

    with AutonomyCycleEngine(
        config, work_source=Batch(), decision_engine=PickLast()
    ) as engine:
        record = engine.run_cycle()

    # A different decision layer produced a different execution target.
    assert record.task_key == "issue-303:retrieve-evidence"
    assert record.decision["decider"] == "pick-last"
    assert record.evidence["task_key"] == "issue-303:retrieve-evidence"


# ---------------------------------------------------------------------------
# Admission dedup
# ---------------------------------------------------------------------------


def test_duplicate_work_is_not_admitted_twice(tmp_path):
    """The same item offered repeatedly must not create duplicate queue entries."""

    class RepeatingSource:
        name = "repeating"

        def discover(self, cycle):
            return [work(400)]  # the identical item, every single cycle

    config = EngineConfig(
        run_id="dedup",
        db_url=f"sqlite:///{tmp_path / 'r.db'}",
        journal_path=tmp_path / "j.json",
    )
    with AutonomyCycleEngine(config, work_source=RepeatingSource()) as engine:
        first = engine.run_cycle()
        second = engine.run_cycle()

    assert first.admission["admitted"] == 1
    assert second.admission["admitted"] == 0
    assert second.admission["deduplicated"] == 1
    # Never re-executed.
    assert second.status == "no-work"


def test_admission_is_bounded_per_cycle(tmp_path):
    """A flood of work cannot blow past the per-cycle admission bound."""

    class FloodSource:
        name = "flood"

        def discover(self, cycle):
            return [work(500 + i) for i in range(50)]

    config = EngineConfig(
        run_id="flood",
        db_url=f"sqlite:///{tmp_path / 'r.db'}",
        journal_path=tmp_path / "j.json",
        max_admissions_per_cycle=3,
    )
    with AutonomyCycleEngine(config, work_source=FloodSource()) as engine:
        record = engine.run_cycle()

    assert record.admission["admitted"] == 3
