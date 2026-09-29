"""Cross-process restart continuity proof for the canonical autonomy engine.

The parent test launches three independent Python interpreters against one
file-backed reservoir and one journal.  The first process exits abruptly while
holding a lease; the second recovers that lease and completes three consecutive
cycles; the third replays the same work and proves completion is not duplicated.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_PROBE = r"""
import json
import os
import sys
from pathlib import Path

from app.calyx_orchestrator.deep_orchestrate import TaskState
from runtime.autonomy_cycle_engine import (
    AutonomyCycleEngine,
    EngineConfig,
    StaticWorkSource,
    normalize_work,
)

phase = sys.argv[1]
storage = Path(sys.argv[2])
storage.mkdir(parents=True, exist_ok=True)
config = EngineConfig(
    run_id="process-restart-continuity",
    db_url=f"sqlite:///{storage / 'reservoir.db'}",
    journal_path=storage / "journal.json",
    lease_ttl_seconds=0.0,
)

def item(number):
    return {
        "number": number,
        "title": f"Process restart proof item {number}",
        "repo": "orchid-calyx-backend",
        "priority": 1,
    }

if phase == "seed":
    engine = AutonomyCycleEngine(
        config,
        work_source=StaticWorkSource(backlog=[item(9901)]),
    )
    first = engine.run_cycle()
    interrupted = normalize_work(item(9902), source="process-probe").to_leaf()
    engine.reservoir.register(interrupted)
    engine.reservoir.lease(interrupted.key, holder="worker-that-exited")
    engine.reservoir.advance(interrupted.key, state=TaskState.RUNNING)
    print(
        json.dumps(
            {
                "status": first.status,
                "task_key": first.task_key,
                "active_before_exit": len(engine.reservoir.active_tasks()),
            }
        ),
        flush=True,
    )
    # Deliberately skip close(), destructors and finally blocks.  The next
    # interpreter must recover only from persisted state.
    os._exit(0)

if phase == "recover":
    engine = AutonomyCycleEngine(
        config,
        work_source=StaticWorkSource(backlog=[item(9903), item(9904)]),
    )
    records = [engine.run_cycle() for _ in range(3)]
    tasks = engine.reservoir.to_dict()["tasks"]
    payload = {
        "statuses": [record.status for record in records],
        "task_keys": [record.task_key for record in records],
        "recovery_kinds": [
            entry["kind"] for record in records for entry in record.recovery
        ],
        "provider_calls": [
            record.evidence.get("provider_api_called") for record in records
        ],
        "completed": sorted(
            key
            for key, task in tasks.items()
            if task["state"] == TaskState.COMPLETED
        ),
        "task_count": len(tasks),
        "journal_cycles": len(engine.journal.cycles),
    }
    engine.close()
    print(json.dumps(payload), flush=True)
    raise SystemExit(0)

if phase == "replay":
    engine = AutonomyCycleEngine(
        config,
        work_source=StaticWorkSource(
            backlog=[item(9901), item(9902), item(9903), item(9904)]
        ),
    )
    records = [engine.run_cycle() for _ in range(4)]
    tasks = engine.reservoir.to_dict()["tasks"]
    payload = {
        "statuses": [record.status for record in records],
        "deduplicated": sum(
            record.admission.get("deduplicated", 0) for record in records
        ),
        "task_count": len(tasks),
        "completed_count": sum(
            task["state"] == TaskState.COMPLETED for task in tasks.values()
        ),
        "active_count": len(engine.reservoir.active_tasks()),
        "journal_cycles": len(engine.journal.cycles),
    }
    engine.close()
    print(json.dumps(payload), flush=True)
    raise SystemExit(0)

raise SystemExit(f"unknown phase: {phase}")
"""


def _phase(phase: str, storage: Path) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE, phase, str(storage)],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_engine_survives_real_process_exit_and_replays_idempotently(
    tmp_path: Path,
) -> None:
    seed = _phase("seed", tmp_path)
    assert seed == {
        "status": "completed",
        "task_key": "issue-9901:retrieve-evidence",
        "active_before_exit": 1,
    }

    recovered = _phase("recover", tmp_path)
    assert recovered["statuses"] == ["completed", "completed", "completed"]
    assert recovered["task_keys"] == [
        "issue-9902:retrieve-evidence",
        "issue-9903:retrieve-evidence",
        "issue-9904:retrieve-evidence",
    ]
    assert "stale_lease_recovered" in recovered["recovery_kinds"]
    assert recovered["provider_calls"] == [False, False, False]
    assert recovered["task_count"] == 4
    assert recovered["journal_cycles"] == 4
    assert len(recovered["completed"]) == 4

    replayed = _phase("replay", tmp_path)
    assert replayed["statuses"] == ["no-work", "no-work", "no-work", "no-work"]
    assert replayed["deduplicated"] == 4
    assert replayed["task_count"] == 4
    assert replayed["completed_count"] == 4
    assert replayed["active_count"] == 0
    assert replayed["journal_cycles"] == 8
