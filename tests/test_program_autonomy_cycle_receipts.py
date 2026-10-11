"""Durable cycle receipts, truthful autonomy status and graceful worker stop."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.calyx_orchestrator.autonomy_cycles import autonomy_status, record_cycle
from app.calyx_orchestrator.autonomy_policy import ProgramAutonomyPolicy
from app.calyx_orchestrator.operations import _engineering_program_status
from app.calyx_orchestrator.program_models import (
    CalyxAutonomyCycle,
    CalyxProgram,
    CalyxProgramDependency,
    CalyxProgramJob,
)
from app.database import Base

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CalyxProgram.__table__,
            CalyxProgramJob.__table__,
            CalyxProgramDependency.__table__,
            CalyxAutonomyCycle.__table__,
        ],
    )
    return Session(engine)


def _result(
    sequence, *, minutes_ago, productive, category=None, healthy=True, reason=None
):
    finished = NOW - timedelta(minutes=minutes_ago)
    jobs = (
        [{"job_key": f"build:{sequence}:0", "productive": True}] if productive else []
    )
    return {
        "executed": True,
        "started_at": (finished - timedelta(seconds=5)).isoformat(),
        "finished_at": finished.isoformat(),
        "scheduler": {"sequence": sequence, "worker_id": "w1", "poll_seconds": 60},
        "classification": {
            "productive": productive,
            "category": category,
            "healthy": healthy,
        },
        "cycle": {
            "completed_jobs": len(jobs),
            "productive_jobs": len(jobs),
            "failed_jobs": 0,
            "jobs": jobs,
            "zero_execution": None if productive else {"reason_code": reason},
        },
        "replenishment": {
            "zero_reason": None if productive else category,
            "detail": None,
            "submissions": [{"work_id": f"work-{sequence}", "outcome": "submitted"}]
            if productive
            else [],
            "reconciled": [],
        },
    }


def test_no_recorded_cycles_is_reported_as_such_not_as_readiness():
    with _db() as db:
        status = autonomy_status(db, owner="owner", now=NOW)
    assert status["state"] == "no_cycles_recorded"
    assert status["heartbeat"] is None and status["last_productive"] is None


def test_status_separates_heartbeat_from_delivered_work():
    with _db() as db:
        record_cycle(
            db,
            _result(1, minutes_ago=5, productive=True),
            owner="owner",
            deployment_commit="a" * 40,
        )
        status = autonomy_status(db, owner="owner", now=NOW)
        assert status["state"] == "productive"
        assert status["heartbeat"]["fresh"] is True
        assert status["last_productive"]["job_keys"] == ["build:1:0"]
        assert status["last_productive"]["replenishment"]["submitted"] == [
            {"work_id": "work-1", "outcome": "submitted"}
        ]
        assert status["last_cycle"]["deployment_commit"] == "a" * 40

        # A live scheduler that delivers nothing is healthy waiting, and the
        # last productive cycle is still reported, not overwritten.
        record_cycle(
            db,
            _result(
                2,
                minutes_ago=4,
                productive=False,
                category="capacity_exhausted",
                reason="ALREADY_RUNNING",
            ),
            owner="owner",
        )
        status = autonomy_status(db, owner="owner", now=NOW)
        assert status["state"] == "healthy_waiting"
        assert status["consecutive_nonproductive"] == 1
        assert status["last_productive"]["sequence"] == 1
        assert status["last_cycle"]["reason_code"] == "ALREADY_RUNNING"

        record_cycle(
            db,
            _result(
                3,
                minutes_ago=3,
                productive=False,
                category="no_executor",
                healthy=False,
                reason="AUTHORITATIVE_EXECUTOR_NOT_REGISTERED",
            ),
            owner="owner",
        )
        status = autonomy_status(db, owner="owner", now=NOW)
        assert status["state"] == "defect"
        assert status["last_defect"]["category"] == "no_executor"
        assert status["consecutive_nonproductive"] == 2
        assert status["recent"] == {
            "window": 3,
            "productive": 1,
            "categories": {"capacity_exhausted": 1, "no_executor": 1},
        }

        # No cycle for well past two polls: the scheduler is stale whatever the
        # last cycle said.
        stale = autonomy_status(db, owner="owner", now=NOW + timedelta(hours=1))
        assert stale["state"] == "stale" and stale["heartbeat"]["fresh"] is False
        # Owners never see each other's cycles.
        assert (
            autonomy_status(db, owner="other", now=NOW)["state"] == "no_cycles_recorded"
        )


def test_failed_cycle_is_recorded_as_scheduler_defect():
    with _db() as db:
        record_cycle(
            db,
            {
                "executed": False,
                "reason": "cycle_failed",
                "error": {"exception_type": "OperationalError"},
                "classification": {
                    "productive": False,
                    "category": "scheduler_defect",
                    "healthy": False,
                },
                "scheduler": {"sequence": 1, "worker_id": "w1", "poll_seconds": 60},
            },
            owner="owner",
        )
        row = db.scalar(select(CalyxAutonomyCycle))
        assert (row.productive, row.category, row.reason_code) == (
            False,
            "scheduler_defect",
            "cycle_failed",
        )


def test_engineering_status_exposes_recorded_autonomy():
    with _db() as db:
        record_cycle(db, _result(1, minutes_ago=0, productive=True), owner="owner")
        status = _engineering_program_status(db, owner="owner")
    assert status["autonomy"]["last_productive"]["job_keys"] == ["build:1:0"]


def test_run_forever_records_each_cycle_and_stops_without_another_sleep(monkeypatch):
    import runtime.program_autonomy_worker as worker

    policy = ProgramAutonomyPolicy(enabled=True, owner="owner", poll_seconds=60)
    calls = iter(
        [{"executed": True, "cycle": {}}, RuntimeError("db down"), {"executed": True}]
    )

    def fake_run_once(_policy, **_kwargs):
        item = next(calls)
        if isinstance(item, Exception):
            raise item
        return dict(item)

    monkeypatch.setattr(worker, "run_once", fake_run_once)
    recorded, sleeps, seen = [], [], []
    stop = threading.Event()

    def recorder(result):
        if result["scheduler"]["sequence"] == 3:
            raise OSError("receipt store unavailable")
        recorded.append(result["scheduler"]["sequence"])
        return f"cycle-{result['scheduler']['sequence']}"

    def on_cycle(result):
        seen.append(result)
        if len(seen) == 3:
            stop.set()

    worker.run_forever(
        policy, sleeper=sleeps.append, on_cycle=on_cycle, recorder=recorder, stop=stop
    )
    assert recorded == [1, 2]
    assert seen[1]["classification"]["category"] == "scheduler_defect"
    assert seen[0]["receipt"] == {"persisted": True, "cycle_id": "cycle-1"}
    assert seen[2]["receipt"] == {
        "persisted": False,
        "error": {"exception_type": "OSError"},
    }
    # Two sleeps between three cycles; none after the stop request.
    assert sleeps == [60, 60]


CHILD = textwrap.dedent(
    """
    import sys, time, threading
    import runtime.program_autonomy_worker as worker
    from app.calyx_orchestrator.autonomy_policy import ProgramAutonomyPolicy

    cycle_seconds = float(sys.argv[1])

    def fake_run_once(_policy, **_kwargs):
        print("cycle-start", flush=True)
        time.sleep(cycle_seconds)
        print("cycle-end", flush=True)
        return {"executed": True}

    worker.run_once = fake_run_once
    stop = threading.Event()
    worker.install_stop_handlers(stop)
    worker.run_forever(
        ProgramAutonomyPolicy(enabled=True, owner="owner", poll_seconds=3600),
        stop=stop,
    )
    print("stopped", flush=True)
    """
)


def _spawn(cycle_seconds: float) -> subprocess.Popen:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    return subprocess.Popen(
        [sys.executable, "-c", CHILD, str(cycle_seconds)],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _await_line(proc: subprocess.Popen, expected: str) -> None:
    line = proc.stdout.readline().strip()
    assert line == expected, (
        line,
        proc.stderr.read() if proc.poll() is not None else "",
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_sigterm_interrupts_the_poll_sleep_and_exits_cleanly():
    proc = _spawn(0)
    _await_line(proc, "cycle-start")
    _await_line(proc, "cycle-end")
    time.sleep(0.3)  # now sleeping for a 3600 s poll
    started = time.monotonic()
    proc.send_signal(signal.SIGTERM)
    out, _ = proc.communicate(timeout=15)
    assert proc.returncode == 0
    assert out.split() == ["stopped"]
    assert time.monotonic() - started < 10


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_sigterm_during_a_cycle_lets_it_finish_then_stops():
    proc = _spawn(1.5)
    _await_line(proc, "cycle-start")
    proc.send_signal(signal.SIGTERM)
    out, err = proc.communicate(timeout=15)
    assert proc.returncode == 0, err
    # The running cycle completed (its leases settle) and no new cycle began.
    assert out.split() == ["cycle-end", "stopped"]


def test_receipt_json_columns_round_trip():
    with _db() as db:
        record_cycle(db, _result(7, minutes_ago=1, productive=True), owner="owner")
        row = db.scalar(select(CalyxAutonomyCycle))
        assert json.loads(row.job_keys_json) == ["build:7:0"]
        assert json.loads(row.replenishment_json)["submitted"][0]["work_id"] == "work-7"
