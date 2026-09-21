#!/usr/bin/env python3
"""Durable ten-cycle autonomy proof with adversarial recovery.

Runs the real ``runtime.autonomy_cycle_engine`` loop against durable on-disk
storage and records per-cycle evidence.

What this proves
----------------
Ten consecutive cycles complete against **one** reservoir database and **one**
journal, with no human intervention and no manual state reset between them.
Each cycle carries the previous cycles' state forward, so a defect in
persistence, deduplication, leasing, or settlement shows up as a failed cycle
rather than being hidden by a fresh database.

Before the ten counted cycles, the proof deliberately breaks the system and
requires it to recover, restarting the engine process-style against the same
storage. Recovery cycles are reported separately and are **not** counted toward
the ten: a recovered failure is evidence that self-healing works, not evidence
of a successful work cycle.

What this does not prove
------------------------
This is the deterministic, provider-free core. It does not exercise a paid
model provider, a GitHub credential, an external scheduler, or a Render
deployment. Those need production evidence of their own and are reported as
such, never inferred from this run.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from app.calyx_orchestrator.deep_orchestrate import TaskState
from runtime.autonomy_cycle_engine import (
    AutonomyCycleEngine,
    EngineConfig,
    ProviderIsolatedExecutor,
    ProviderUnavailable,
    StaticWorkSource,
    TransientExecutionError,
    load_canonical_context,
)

PROOF_SCHEMA = "oc.autonomy-durable-proof.v1"
TARGET_CYCLES = 10
_ADVERSARIAL_BASE = 8500
_PROOF_BASE = 9100


def work(number: int, priority: int = 1) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"Autonomy durable proof item {number}",
        "repo": "orchid-continuum-frontend",
        "priority": priority,
    }


def _engine(
    storage: Path,
    backlog: list[dict[str, Any]],
    *,
    run_id: str,
    executor: Any = None,
    lease_ttl_seconds: float = 300.0,
) -> AutonomyCycleEngine:
    return AutonomyCycleEngine(
        EngineConfig(
            run_id=run_id,
            db_url=f"sqlite:///{storage / 'reservoir.db'}",
            journal_path=storage / "journal.json",
            lease_ttl_seconds=lease_ttl_seconds,
        ),
        work_source=StaticWorkSource(backlog=list(backlog)),
        executor=executor,
    )


def run_adversarial_phase(storage: Path, run_id: str) -> list[dict[str, Any]]:
    """Break the system on purpose, then require it to keep working."""
    scenarios: list[dict[str, Any]] = []

    # --- Scenario 1: provider unavailable, then a transient fault ----------
    key_provider = f"issue-{_ADVERSARIAL_BASE + 1}:retrieve-evidence"
    key_transient = f"issue-{_ADVERSARIAL_BASE + 2}:retrieve-evidence"
    executor = ProviderIsolatedExecutor(
        failure_plan={
            key_provider: [ProviderUnavailable("model provider lane unreachable")],
            key_transient: [TransientExecutionError("connection reset by peer")],
        }
    )
    engine = _engine(
        storage,
        [work(_ADVERSARIAL_BASE + 1), work(_ADVERSARIAL_BASE + 2)],
        run_id=run_id,
        executor=executor,
    )
    try:
        provider_cycle = engine.run_cycle()
        scenarios.append(
            {
                "scenario": "F1 provider unavailable",
                "expected": "work deferred and classified; orchestration loop survives",
                "observed": provider_cycle.status,
                "classification": provider_cycle.execution.get("classification"),
                "loop_alive": True,
                "passed": provider_cycle.status == "deferred"
                and provider_cycle.execution.get("classification")
                == "provider_unavailable",
            }
        )

        transient_cycle = engine.run_cycle()
        retries = [
            entry
            for entry in transient_cycle.recovery
            if entry["kind"] == "transient_error_retried"
        ]
        scenarios.append(
            {
                "scenario": "F2 transient execution fault",
                "expected": "retried inside the cycle and completed",
                "observed": transient_cycle.status,
                "retries": len(retries),
                "passed": transient_cycle.status == "completed" and len(retries) == 1,
            }
        )

        # --- Scenario 2: malformed work item ------------------------------
        class MalformedSource:
            name = "malformed-probe"

            def __init__(self) -> None:
                self.served = False

            def discover(self, cycle: int) -> list[Any]:
                if self.served:
                    return []
                self.served = True
                return ["not-a-dict", {"number": -7}, work(_ADVERSARIAL_BASE + 3)]

        engine.work_source = MalformedSource()
        malformed_cycle = engine.run_cycle()
        scenarios.append(
            {
                "scenario": "C malformed work item",
                "expected": "bad payloads rejected with reasons; valid work still runs",
                "observed": malformed_cycle.status,
                "rejected": malformed_cycle.admission.get("rejected"),
                "reasons": [r["reason"] for r in malformed_cycle.rejected],
                "passed": malformed_cycle.status == "completed"
                and malformed_cycle.admission.get("rejected") == 2,
            }
        )

        # --- Scenario 3: duplicate completion -----------------------------
        settled_key = malformed_cycle.task_key
        original_evidence = dict(engine.reservoir.get(settled_key).evidence)
        replay = engine.reservoir.settle(
            settled_key,
            evidence={"worker_id": "impostor", "status": "tampered"},
            require_lease=True,
            holder=engine.config.lease_holder,
        )
        preserved = engine.reservoir.get(settled_key).evidence == original_evidence
        scenarios.append(
            {
                "scenario": "G duplicate completion request",
                "expected": "replay suppressed; settled evidence unchanged",
                "observed": f"settled={replay.settled} duplicate={replay.duplicate}",
                "evidence_preserved": preserved,
                "passed": replay.duplicate is True
                and replay.settled is False
                and preserved,
            }
        )

        # --- Scenario 4: completion without a lease -----------------------
        from app.calyx_orchestrator.deep_orchestrate import (
            AUTH_WORKSPACE,
            Priority,
            TaskLeaf,
        )

        unleased_key = f"issue-{_ADVERSARIAL_BASE + 4}:retrieve-evidence"
        engine.reservoir.register(
            TaskLeaf(
                key=unleased_key,
                title="unleased",
                repo="r",
                module="m",
                priority=Priority.P2,
                authority_class=AUTH_WORKSPACE,
                consequence_risk="low",
                issue_number=_ADVERSARIAL_BASE + 4,
                acceptance_criteria=["a"],
            )
        )
        try:
            engine.reservoir.settle(
                unleased_key, evidence={"x": 1}, require_lease=True
            )
            refused = False
            detail = "completion was allowed without a lease"
        except PermissionError as exc:
            refused = True
            detail = str(exc)
        scenarios.append(
            {
                "scenario": "B/G completion without ownership",
                "expected": "refused: completion requires an active lease",
                "observed": detail,
                "passed": refused,
            }
        )

        # --- Scenario 5: duplicate lease attempt --------------------------
        engine.reservoir.lease(unleased_key, holder="worker-a")
        try:
            engine.reservoir.lease(unleased_key, holder="worker-b")
            prevented = False
            detail = "a second holder acquired a held lease"
        except ValueError as exc:
            prevented = True
            detail = str(exc)
        scenarios.append(
            {
                "scenario": "B duplicate lease attempt",
                "expected": "refused: a held task cannot be leased again",
                "observed": detail,
                "passed": prevented,
            }
        )
        engine.reservoir.block(unleased_key, reason="adversarial-probe-cleanup")
    finally:
        engine.close()

    # --- Scenario 6: worker interruption + restart ------------------------
    interrupted_key = f"issue-{_ADVERSARIAL_BASE + 5}:retrieve-evidence"
    crashed = _engine(storage, [], run_id=run_id)
    from app.calyx_orchestrator.deep_orchestrate import (
        AUTH_WORKSPACE,
        Priority,
        TaskLeaf,
    )

    crashed.reservoir.register(
        TaskLeaf(
            key=interrupted_key,
            title="interrupted work",
            repo="r",
            module="m",
            priority=Priority.P1,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            issue_number=_ADVERSARIAL_BASE + 5,
            acceptance_criteria=["a"],
        )
    )
    crashed.reservoir.lease(interrupted_key, holder="worker-that-died")
    crashed.reservoir.advance(interrupted_key, state=TaskState.RUNNING)
    # Abrupt termination: no settle, no journal flush, no clean close.
    crashed._session.close()
    crashed._engine.dispose()

    # --- Scenario 7: corrupt the persisted journal before restart ---------
    journal_path = storage / "journal.json"
    pre_corruption = json.loads(journal_path.read_text(encoding="utf-8"))
    cycles_before = len(pre_corruption.get("cycles", []))
    journal_path.write_text('{"schema": "oc.autonomy-cycle-jour', encoding="utf-8")

    restarted = _engine(storage, [], run_id=run_id, lease_ttl_seconds=0.0)
    try:
        recovery_cycle = restarted.run_cycle()
        kinds = {entry["kind"] for entry in recovery_cycle.recovery}

        # Reconciliation frees every abandoned task at once, so the decision
        # layer may legitimately run a different recovered task first. What
        # matters is that the interrupted work is reclaimed and then finished,
        # not that it happens to be chosen in this particular cycle.
        drained: list[str] = [recovery_cycle.status]
        for _ in range(6):
            task = restarted.reservoir.get(interrupted_key)
            if task is not None and task.state == TaskState.COMPLETED:
                break
            drained.append(restarted.run_cycle().status)
        interrupted_task = restarted.reservoir.get(interrupted_key)
        scenarios.append(
            {
                "scenario": "D worker interruption and restart",
                "expected": "abandoned lease reclaimed and the work finished",
                "observed": (
                    f"reclaimed={'stale_lease_recovered' in kinds} "
                    f"final_state={interrupted_task.state if interrupted_task else None} "
                    f"cycles={drained}"
                ),
                "passed": "stale_lease_recovered" in kinds
                and interrupted_task is not None
                and interrupted_task.state == TaskState.COMPLETED,
            }
        )
        scenarios.append(
            {
                "scenario": "J partial/corrupt persisted state",
                "expected": "corrupt journal recovered; engine still operates",
                "observed": f"journal_recovered={'journal_recovered' in kinds}",
                "cycles_lost_to_corruption": cycles_before,
                "passed": "journal_recovered" in kinds
                and recovery_cycle.status == "completed",
            }
        )

        # --- Scenario 8: queue starvation ---------------------------------
        # Drain whatever recovery left queued, then confirm the empty queue is
        # reported honestly rather than crashing or inventing a success.
        starved = restarted.run_cycle()
        for _ in range(8):
            if starved.status == "no-work":
                break
            starved = restarted.run_cycle()
        scenarios.append(
            {
                "scenario": "H queue empty / starvation",
                "expected": "reported as no-work; no crash and no fabricated success",
                "observed": (
                    f"status={starved.status} "
                    f"starved={starved.replenishment.get('starved')} "
                    f"decision={starved.decision.get('action')}"
                ),
                "passed": starved.status == "no-work"
                and starved.replenishment.get("starved") is True,
            }
        )
    finally:
        restarted.close()

    # --- Scenario 9: invalid autonomy context version ---------------------
    from runtime.autonomy_cycle_engine import ContextVersionError

    bad_context = load_canonical_context()
    bad_context["version"] = "2.0.0"
    try:
        AutonomyCycleEngine(
            EngineConfig(
                run_id=f"{run_id}-badctx",
                db_url="sqlite:///:memory:",
                journal_path=None,
            ),
            work_source=StaticWorkSource(backlog=[]),
            context=bad_context,
        )
        refused_ctx = False
        ctx_detail = "engine started under an unsupported context version"
    except ContextVersionError as exc:
        refused_ctx = True
        ctx_detail = str(exc)
    scenarios.append(
        {
            "scenario": "I mismatched autonomy context version",
            "expected": "engine refuses to start; fails closed",
            "observed": ctx_detail,
            "passed": refused_ctx,
        }
    )

    # --- Scenario 10: stale lease recovery (explicit) ---------------------
    stale_key = f"issue-{_ADVERSARIAL_BASE + 6}:retrieve-evidence"
    stale_engine = _engine(storage, [], run_id=run_id, lease_ttl_seconds=0.0)
    try:
        stale_engine.reservoir.register(
            TaskLeaf(
                key=stale_key,
                title="stale lease probe",
                repo="r",
                module="m",
                priority=Priority.P1,
                authority_class=AUTH_WORKSPACE,
                consequence_risk="low",
                issue_number=_ADVERSARIAL_BASE + 6,
                acceptance_criteria=["a"],
            )
        )
        stale_engine.reservoir.lease(stale_key, holder="abandoning-worker")
        stale_cycle = stale_engine.run_cycle()
        kinds = {entry["kind"] for entry in stale_cycle.recovery}
        scenarios.append(
            {
                "scenario": "A stale lease recovery",
                "expected": "expired lease reclaimed and the work re-run",
                "observed": f"status={stale_cycle.status} recovery={sorted(kinds)}",
                "passed": "stale_lease_recovered" in kinds
                and stale_cycle.status == "completed",
            }
        )
    finally:
        stale_engine.close()

    # --- Scenario 11: validation failure ----------------------------------
    class EmptyOutputWorker:
        def execute(self, leaf):
            from app.calyx_orchestrator.leaf_worker import TaskExecutionResult

            return TaskExecutionResult(
                task_key=leaf.key,
                worker_id="empty-output-worker",
                status="completed",
                started_at="2026-09-21T00:00:00+00:00",
                completed_at="2026-09-21T00:00:01+00:00",
                duration_seconds=1.0,
                output={},
            )

    validation_engine = _engine(
        storage,
        [work(_ADVERSARIAL_BASE + 7)],
        run_id=run_id,
        executor=EmptyOutputWorker(),
    )
    try:
        failed_cycle = validation_engine.run_cycle()
        parked = validation_engine.reservoir.get(failed_cycle.task_key or "")
        scenarios.append(
            {
                "scenario": "E validation failure",
                "expected": "not completed; parked for repair with a recorded reason",
                "observed": f"status={failed_cycle.status} reason={failed_cycle.failure_reason}",
                "task_state": parked.state if parked else None,
                "passed": failed_cycle.status == "validation-failed"
                and parked is not None
                and parked.state == TaskState.REPAIR_BACKOFF,
            }
        )
    finally:
        validation_engine.close()

    return scenarios


def run_proof(storage: Path, run_id: str) -> dict[str, Any]:
    context = load_canonical_context()
    target = int(context["evaluation"]["autonomy_proof_target"])

    adversarial = run_adversarial_phase(storage, f"{run_id}-adversarial")

    # The counted ten. One engine, one durable store, no resets.
    backlog = [work(_PROOF_BASE + i) for i in range(1, target + 1)]
    engine = _engine(storage, backlog, run_id=run_id)
    try:
        records = engine.run_cycles(target)
        journal_cycles = len(engine.journal.cycles)
        reservoir_state = engine.reservoir.to_dict().get("tasks", {})
    finally:
        engine.close()

    cycles: list[dict[str, Any]] = []
    for record in records:
        cycles.append(
            {
                "cycle": record.cycle,
                "run_id": record.run_id,
                "status": record.status,
                "work_id": record.task_key,
                "issue_number": record.issue_number,
                "source_of_work": record.work_source,
                "admission": {
                    "discovered": record.admission.get("discovered"),
                    "admitted": record.admission.get("admitted"),
                    "rejected": record.admission.get("rejected"),
                    "deduplicated": record.admission.get("deduplicated"),
                },
                "lease_id": record.lease.get("lease_id"),
                "lease_owner": record.lease.get("holder"),
                "decision": {
                    "decider": record.decision.get("decider"),
                    "action": record.decision.get("action"),
                    "selected": record.decision.get("selected_key"),
                    "deferred": record.decision.get("deferred"),
                    "rationale": record.decision.get("rationale"),
                },
                "execution": record.execution,
                "validation": {
                    "passed": record.validation.get("passed"),
                    "checks": len(record.validation.get("checks", [])),
                },
                "evidence": record.evidence,
                "settlement": record.settlement,
                "replenishment": record.replenishment,
                "recovery_used": record.recovery,
                "started_at": record.started_at,
                "ended_at": record.ended_at,
            }
        )

    completed = [c for c in cycles if c["status"] == "completed"]
    consecutive = 0
    for cycle in cycles:
        if cycle["status"] != "completed":
            break
        consecutive += 1

    distinct_work = {c["work_id"] for c in completed}
    provider_calls = sum(
        1 for c in completed if c["evidence"].get("provider_api_called")
    )
    missing_evidence = sum(
        1 for c in completed if not c["evidence"].get("required_evidence_satisfied")
    )
    unsettled = sum(1 for c in completed if not c["settlement"].get("settled"))
    duplicate_settlements = sum(
        1 for c in completed if c["settlement"].get("duplicate_suppressed")
    )

    adversarial_passed = sum(1 for s in adversarial if s["passed"])
    adversarial_failed = [s["scenario"] for s in adversarial if not s["passed"]]

    status = (
        "PASS"
        if (
            consecutive == target
            and len(distinct_work) == target
            and provider_calls == 0
            and missing_evidence == 0
            and unsettled == 0
            and duplicate_settlements == 0
            and not adversarial_failed
        )
        else "FAIL"
    )

    return {
        "schema": PROOF_SCHEMA,
        "status": status,
        "target": target,
        "consecutive_completed_cycles": consecutive,
        "distinct_work_items": len(distinct_work),
        "provider_calls": provider_calls,
        "missing_completion_evidence": missing_evidence,
        "unsettled_completions": unsettled,
        "duplicate_settlements": duplicate_settlements,
        "durable_storage": {
            "reservoir": "sqlite file, shared by every cycle",
            "journal_cycles_persisted": journal_cycles,
            "reservoir_tasks_persisted": len(reservoir_state),
            "state_reset_between_cycles": False,
        },
        "canonical_context": {
            "schema": context["schema"],
            "version": context["version"],
        },
        "adversarial_scenarios": {
            "total": len(adversarial),
            "passed": adversarial_passed,
            "failed": adversarial_failed,
            "detail": adversarial,
        },
        "cycles": cycles,
        "scope_note": (
            "Proves the deterministic provider-free autonomy core on durable "
            "storage. Does not prove paid-provider execution, GitHub "
            "credentialed dispatch, external scheduling, or Render deployment "
            "health; those require production evidence of their own."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="artifacts/autonomy-durable-proof.json",
        help="where to write the proof artifact",
    )
    parser.add_argument(
        "--storage",
        default=None,
        help="durable storage directory (default: a temporary directory)",
    )
    parser.add_argument("--run-id", default="autonomy-durable-proof")
    parser.add_argument(
        "--quiet", action="store_true", help="only print the summary verdict"
    )
    args = parser.parse_args()

    temporary = args.storage is None
    storage = Path(args.storage) if args.storage else Path(tempfile.mkdtemp())
    storage.mkdir(parents=True, exist_ok=True)

    try:
        result = run_proof(storage, args.run_id)
    finally:
        if temporary:
            shutil.rmtree(storage, ignore_errors=True)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    if args.quiet:
        print(
            f"{result['status']}: {result['consecutive_completed_cycles']}"
            f"/{result['target']} consecutive cycles, "
            f"{result['adversarial_scenarios']['passed']}"
            f"/{result['adversarial_scenarios']['total']} adversarial scenarios"
        )
    else:
        print(json.dumps(result, indent=2))

    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
