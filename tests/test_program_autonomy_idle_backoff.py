"""Idle backoff and explicit idle diagnostics for the scheduled autonomy loop.

Regression for the hosted acceptance run: after its 17-program manifest was
delivered, the worker kept polling every 30 s and recorded 2,390 identical
IDLE_NO_CANDIDATE cycles. The real reason (WORK_MANIFEST_COMPLETED) was visible
only inside replenishment_json, and status reported "healthy_waiting" with a
non-productive count capped at the recent window.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import runtime.program_autonomy_worker as worker
from app.calyx_orchestrator.autonomy_cycles import (
    RECENT_WINDOW,
    autonomy_status,
    record_cycle,
)
from app.calyx_orchestrator.autonomy_policy import ProgramAutonomyPolicy
from app.calyx_orchestrator.program_models import CalyxAutonomyCycle
from app.database import Base

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
IDLE = {"productive": False, "category": "no_eligible_work", "healthy": True}
PRODUCTIVE = {"productive": True, "category": None, "healthy": True}
DEFECT = {"productive": False, "category": "scheduler_defect", "healthy": False}


def _policy(**overrides) -> ProgramAutonomyPolicy:
    values = {
        "enabled": True,
        "owner": "owner",
        "poll_seconds": 30,
        "idle_backoff_after": 2,
        "idle_max_seconds": 100,
    }
    values.update(overrides)
    return ProgramAutonomyPolicy(**values)


def test_next_sleep_is_bounded_and_doubles_only_after_the_threshold():
    policy = _policy()
    assert [policy.next_sleep_seconds(n) for n in range(6)] == [
        30,
        30,
        60,
        100,
        100,
        100,
    ]
    # A cap below the poll interval never shortens the normal cadence.
    assert _policy(idle_max_seconds=15).next_sleep_seconds(50) == 30
    # Huge streaks do not overflow.
    assert _policy().next_sleep_seconds(10**6) == 100


def test_idle_settings_are_read_and_bounded_from_the_environment():
    env = {
        "CALYX_PROGRAM_AUTONOMY_ENABLED": "true",
        "CALYX_PROGRAM_AUTONOMY_OWNER": "owner",
        "CALYX_PROGRAM_AUTONOMY_IDLE_BACKOFF_AFTER": "5",
        "CALYX_PROGRAM_AUTONOMY_IDLE_MAX_SECONDS": "600",
    }
    policy = ProgramAutonomyPolicy.from_environ(env)
    assert (policy.idle_backoff_after, policy.idle_max_seconds) == (5, 600)
    defaults = ProgramAutonomyPolicy.from_environ(
        {k: v for k, v in env.items() if "IDLE" not in k}
    )
    assert (defaults.idle_backoff_after, defaults.idle_max_seconds) == (10, 900)
    with pytest.raises(ValueError, match="IDLE_MAX_SECONDS_OUT_OF_RANGE"):
        ProgramAutonomyPolicy.from_environ(
            {**env, "CALYX_PROGRAM_AUTONOMY_IDLE_MAX_SECONDS": "5"}
        )


def test_loop_backs_off_on_idle_and_resets_on_work_or_defect(monkeypatch):
    plan = iter([IDLE, IDLE, IDLE, IDLE, PRODUCTIVE, IDLE, IDLE, IDLE, DEFECT, IDLE])
    monkeypatch.setattr(
        worker,
        "run_once",
        lambda _policy, **_kw: {"executed": True, "classification": dict(next(plan))},
    )
    sleeps: list[float] = []
    seen: list[dict] = []
    stop = threading.Event()

    def on_cycle(result):
        seen.append(result["scheduler"])
        if len(seen) == 10:
            stop.set()

    worker.run_forever(_policy(), sleeper=sleeps.append, on_cycle=on_cycle, stop=stop)
    assert sleeps == [30, 60, 100, 100, 30, 30, 60, 100, 30]
    assert [s["idle_streak"] for s in seen] == [1, 2, 3, 4, 0, 1, 2, 3, 0, 1]
    assert all(s["poll_seconds"] == 30 for s in seen)
    assert [s["next_sleep_seconds"] for s in seen[:9]] == sleeps


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[CalyxAutonomyCycle.__table__])
    return Session(engine)


def _receipt(sequence, *, finished, classification, detail=None, next_sleep=30):
    productive = classification["productive"]
    return {
        "executed": True,
        "finished_at": finished.isoformat(),
        "scheduler": {
            "sequence": sequence,
            "worker_id": "w1",
            "poll_seconds": 30,
            "idle_streak": 0,
            "next_sleep_seconds": next_sleep,
        },
        "classification": classification,
        "cycle": {
            "productive_jobs": 1 if productive else 0,
            "jobs": [{"job_key": f"k{sequence}", "productive": True}]
            if productive
            else [],
            "zero_execution": None
            if productive
            else {"reason_code": "IDLE_NO_CANDIDATE"},
        },
        "replenishment": {
            "zero_reason": None if productive else "no_eligible_work",
            "detail": detail,
            "submissions": [],
            "reconciled": [],
        },
    }


def test_exhausted_manifest_is_reported_explicitly_with_an_exact_idle_count():
    idle_count = RECENT_WINDOW + 25  # beyond the status window
    with _db() as db:
        start = NOW - timedelta(hours=2)
        record_cycle(
            db,
            _receipt(1, finished=start, classification=PRODUCTIVE),
            owner="owner",
        )
        for n in range(idle_count):
            record_cycle(
                db,
                _receipt(
                    n + 2,
                    finished=start + timedelta(minutes=1 + n),
                    classification=IDLE,
                    detail="WORK_MANIFEST_COMPLETED",
                    next_sleep=900 if n == idle_count - 1 else 30,
                ),
                owner="owner",
            )
        # The last cycle finished 14 minutes ago with a 900 s backoff: still a
        # live scheduler, not a stale one.
        status = autonomy_status(
            db, owner="owner", now=start + timedelta(minutes=idle_count + 14)
        )
    assert status["state"] == "healthy_waiting"
    assert status["heartbeat"]["fresh"] is True
    assert status["consecutive_nonproductive"] == idle_count
    assert status["idle"] == {
        "since": (start + timedelta(minutes=1)).isoformat(),
        "category": "no_eligible_work",
        "reason_code": "IDLE_NO_CANDIDATE",
        "upstream_zero_reason": "no_eligible_work",
        "upstream_detail": "WORK_MANIFEST_COMPLETED",
        "work_supply": "static_manifest_exhausted",
        "next_cycle_within_seconds": 900,
    }


@pytest.mark.parametrize(
    ("detail", "supply"),
    [
        ("WORK_SOURCES_DRAINED", "sources_drained"),
        ("WORK_SOURCES_IDLE", "sources_idle"),
        ("WORK_SOURCE_FAILED:traitbank_intake", "source_failed"),
        ("SOMETHING_NEW", "unknown"),
    ],
)
def test_work_supply_names_the_upstream_reason(detail, supply):
    with _db() as db:
        record_cycle(
            db,
            _receipt(1, finished=NOW, classification=IDLE, detail=detail),
            owner="owner",
        )
        status = autonomy_status(db, owner="owner", now=NOW)
    assert status["idle"]["work_supply"] == supply
    assert status["consecutive_nonproductive"] == 1


def test_productive_latest_cycle_has_no_idle_block():
    with _db() as db:
        record_cycle(
            db, _receipt(1, finished=NOW, classification=PRODUCTIVE), owner="owner"
        )
        status = autonomy_status(db, owner="owner", now=NOW)
    assert status["idle"] is None and status["consecutive_nonproductive"] == 0


def test_receipt_without_a_replenisher_says_so():
    with _db() as db:
        result = _receipt(1, finished=NOW, classification=IDLE)
        result.pop("replenishment")
        record_cycle(db, result, owner="owner")
        status = autonomy_status(db, owner="owner", now=NOW)
    assert status["idle"]["work_supply"] == "no_replenisher"
    assert json.dumps(status)  # JSON-safe
