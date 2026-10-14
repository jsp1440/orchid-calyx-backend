"""Continuous autonomy loop on the real scheduler, routes and executors.

Runs the real ``run_forever`` loop, the real canonical submit and orchestrator
routes, real API-key auth, the real read-only executors (TraitBank verdict,
repository evidence + static validation) and disposable PostgreSQL. Work
comes only from Brain's ``autonomy_loop`` observers. The test proves:

1. Observed gaps (a committed TraitBank batch, unverified source files) are
   executed through claim, lease and receipt, in priority order.
2. Delivered verification becomes the learned baseline. With no gaps left the
   cycle says ``LOOP_NO_GAPS_DETECTED``, and nothing is re-executed.
3. A real source change (a new commit) is discovered and executed once.
4. Governed engineering objectives are proposals: the cycle reports
   ``owner_gate`` / ``AWAITING_APPROVAL`` rather than a silent healthy idle,
   and nothing is executed for them.
"""

# Fixtures are imported from the TraitBank cycle test and then requested as
# parameters, which pyflakes reads as redefinition.
# ruff: noqa: F811

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from test_traitbank_autonomy_cycle import (  # noqa: F401 - fixtures
    BRANCH,
    OWNER,
    REPOSITORY,
    _darwin_batch,
    api,
    engine,
)

import runtime.program_autonomy_worker as worker_module
from app.calyx_orchestrator.autonomy_cycles import autonomy_status, record_cycle
from app.calyx_orchestrator.autonomy_policy import ProgramAutonomyPolicy
from app.calyx_orchestrator.executor_registry import AuthoritativeExecutorRegistry
from app.calyx_orchestrator.program_models import CalyxProgramJob
from app.calyx_orchestrator.pulse_ledger_store import DatabasePulseLedger

BRAIN = os.environ.get("OC_BRAIN_REPO_PATH", "").strip()

pytestmark = [
    pytest.mark.requires_postgres("TEST_DATABASE_URL"),
    pytest.mark.skipif(
        not BRAIN or not (Path(BRAIN) / "calyx_brain" / "autonomy_loop.py").is_file(),
        reason="OC_BRAIN_REPO_PATH must name a Brain checkout with "
        "calyx_brain/autonomy_loop.py",
    ),
]


def _brain():
    if BRAIN not in sys.path:
        sys.path.append(BRAIN)
    from calyx_brain import autonomy_loop, autonomy_pulse

    return autonomy_loop, autonomy_pulse


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True)


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "data" / "traitbank").mkdir(parents=True)
    (root / "app").mkdir()
    _git(root, "init", "-q", "-b", BRANCH)
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Loop fixture")
    (root / "AGENTS.md").write_text("Autonomy loop fixture.\n")
    (root / "requirements.txt").write_text("")
    (root / "data" / "traitbank" / "darwin_1862.json").write_text(
        json.dumps(_darwin_batch(), indent=1, sort_keys=True)
    )
    (root / "app" / "alpha.py").write_text("ALPHA = 1\n")
    (root / "app" / "beta.py").write_text("def beta():\n    return 2\n")
    _commit(root, "fixture")
    # Untracked isolation marker, exactly as the hosted start script writes it.
    (root / ".calyx-isolated-workspace.json").write_text(
        json.dumps(
            {
                "schema": "calyx-isolated-workspace-v1",
                "repository": REPOSITORY,
                "branch": BRANCH,
                "disposable": True,
                "workspace_write_authorized": True,
            }
        )
    )
    queue = tmp_path / "queue.json"
    queue.write_text(
        json.dumps(
            {
                "schema": "oc.autonomy-mission-queue.v1",
                "lanes": [
                    {
                        "id": "control_panel",
                        "missions": [
                            {"id": "CP-001", "objective": "Expose one real status."}
                        ],
                    }
                ],
            }
        )
    )
    return root, queue


def _run_cycles(engine, root, replenish, count):
    registry = AuthoritativeExecutorRegistry(
        workspace_root=root, repository_name=REPOSITORY
    )
    policy = ProgramAutonomyPolicy(
        enabled=True,
        owner=OWNER,
        worker_id="loop-worker",
        poll_seconds=1,
        max_jobs_per_cycle=2,
        lease_seconds=60,
        timeout_seconds=30,
    )
    cycles: list[dict] = []
    stop = threading.Event()

    def on_cycle(result):
        cycles.append(result)
        if len(cycles) == count:
            stop.set()

    def recorder(result):
        with Session(engine) as db:
            return record_cycle(db, result, owner=OWNER)

    watchdog = threading.Timer(120, stop.set)
    watchdog.start()
    try:
        worker_module.run_forever(
            policy,
            on_cycle=on_cycle,
            replenish=replenish,
            registry=registry,
            recorder=recorder,
            stop=stop,
            sleeper=lambda _s: None,
        )
    finally:
        watchdog.cancel()
    assert len(cycles) == count, "scheduler did not complete the expected cycles"
    return cycles


def test_loop_discovers_executes_learns_and_replenishes(engine, api, repo, monkeypatch):
    loop_module, pulse = _brain()
    root, queue = repo
    _client, post, get = api
    monkeypatch.setattr(
        worker_module, "get_session_local", lambda: sessionmaker(engine)
    )
    env = {
        "CALYX_BACKEND_BASE_URL": "http://127.0.0.1:8000",
        "CALYX_API_KEY": os.environ["CALYX_API_KEY"],
    }
    observers = loop_module.observers_from_spec(
        [
            "scientific_batches",
            "repository_changes:app/*.py",
            "completion_feedback",
            f"engineering_objectives:{queue}",
        ],
        workspace=root,
        repository=REPOSITORY,
        branch=BRANCH,
    )
    ledger = DatabasePulseLedger(
        sessionmaker(engine), key="loop", ledger_schema=pulse.LEDGER_SCHEMA
    )

    def replenish():
        return loop_module.run_cycle(
            observers,
            ledger=ledger,
            transport=post,
            status_transport=get,
            env=env,
            max_submissions_per_day=50,
        )

    # 1. Scientific batch first, then the source verification, each executed
    # by the registered read-only executors.
    sci, maint, quiet = _run_cycles(engine, root, replenish, 3)
    assert sci["classification"]["productive"] is True, json.dumps(
        {k: sci.get(k) for k in ("classification", "cycle", "replenishment")},
        default=str,
    )[:3000]
    assert sci["replenishment"]["submissions"][0]["work_id"].startswith(
        "loop:scientific_data_acquisition:"
    )
    assert [j["executor_key"] for j in sci["cycle"]["jobs"]] == [
        "repository_evidence_reader_v1",
        "traitbank_batch_validator_v1",
    ]
    assert maint["classification"]["productive"] is True
    assert maint["replenishment"]["submissions"][0]["work_id"].startswith(
        "loop:maintenance:"
    )
    # 4. With executable gaps exhausted, the engineering objective remains: an
    # explicit owner gate, never a silent healthy idle and never executed.
    assert (
        quiet["replenishment"]["zero_reason"],
        quiet["replenishment"]["detail"],
    ) == ("owner_gate", "AWAITING_APPROVAL:1")
    assert quiet["classification"] == {
        "productive": False,
        "category": "owner_gate",
        "healthy": True,
    }
    state = ledger.load()
    assert set(state["loop"]["verified"]) == {"app/alpha.py", "app/beta.py"}
    (proposal,) = state["loop"]["proposals"].values()
    assert proposal["work_class"] == "engineering_development"

    # 3. A new commit changes one source file: exactly one new verification.
    (root / "app" / "beta.py").write_text("def beta():\n    return 3\n")
    _commit(root, "change beta")
    changed, settled = _run_cycles(engine, root, replenish, 2)
    assert changed["classification"]["productive"] is True
    work_id = changed["replenishment"]["submissions"][0]["work_id"]
    assert work_id.startswith("loop:maintenance:")
    assert list(ledger.load()["loop"]["candidates"][work_id]["facts"]["verifies"]) == [
        "app/beta.py"
    ]
    assert settled["replenishment"]["detail"] == "AWAITING_APPROVAL:1"

    with Session(engine) as db:
        jobs = db.scalars(select(CalyxProgramJob)).all()
        # 3 programs x 2 jobs, each delivered once on its first attempt.
        assert len(jobs) == 6 and len({j.job_key for j in jobs}) == 6
        assert {(j.status, j.outcome, j.attempt_count) for j in jobs} == {
            ("completed", "DELIVERED", 1)
        }
        status = autonomy_status(db, owner=OWNER)
    assert status["idle"]["work_supply"] == "awaiting_approval"
    assert status["idle"]["upstream_detail"] == "AWAITING_APPROVAL:1"
