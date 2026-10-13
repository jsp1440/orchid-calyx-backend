"""Calyx health observer (repair proposals) and read-only proposal visibility."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.calyx_orchestrator.autonomy_observers import (
    CalyxHealthObserver,
    proposals_summary,
)
from app.calyx_orchestrator.program_models import (
    CalyxAutonomyCycle,
    CalyxBrainPulseLedger,
    CalyxProgram,
    CalyxProgramJob,
)
from app.database import Base

BRAIN = os.environ.get("OC_BRAIN_REPO_PATH", "").strip()
NOW = datetime(2026, 10, 13, tzinfo=UTC)
needs_brain = pytest.mark.skipif(
    not BRAIN or not (Path(BRAIN) / "calyx_brain" / "autonomy_loop.py").is_file(),
    reason="OC_BRAIN_REPO_PATH must name a Brain checkout with autonomy_loop.py",
)


@pytest.fixture
def factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CalyxAutonomyCycle.__table__,
            CalyxProgram.__table__,
            CalyxProgramJob.__table__,
            CalyxBrainPulseLedger.__table__,
        ],
    )
    if BRAIN and BRAIN not in sys.path:
        sys.path.append(BRAIN)
    return sessionmaker(engine)


def _cycle(db, n, *, category=None, reason=None, healthy=True, productive=False):
    db.add(
        CalyxAutonomyCycle(
            owner="owner",
            worker_id="w",
            sequence=n,
            poll_seconds=30,
            finished_at=NOW + timedelta(seconds=n),
            productive=productive,
            healthy=healthy,
            category=category,
            reason_code=reason,
        )
    )


@needs_brain
def test_recurring_defects_and_blocked_jobs_become_stable_repair_candidates(factory):
    with factory() as db:
        for n in range(4):
            _cycle(
                db, n, category="no_executor", reason="EXECUTOR_MISSING", healthy=False
            )
        _cycle(db, 10, category="scheduler_defect", reason="ONCE", healthy=False)
        _cycle(db, 11, category="no_eligible_work", reason="IDLE_NO_CANDIDATE")
        db.add(CalyxProgram(program_id="p1", owner="owner", title="t", objective="o"))
        db.add(
            CalyxProgramJob(
                program_job_id="j1",
                program_id="p1",
                job_key="build:x:1",
                role_key="isolated_workspace_static_validator",
                title="t",
                repository="r",
                work_fingerprint="f",
                status="blocked",
                blocker="STATIC_VALIDATION_FAILED:SyntaxError",
            )
        )
        db.commit()
    observer = CalyxHealthObserver(factory, owner="owner")
    first = observer.observe({})
    from calyx_brain.autonomy_loop import REPAIR

    assert [c.work_class for c in first] == [REPAIR, REPAIR]
    assert first[0].evidence == ("category:no_executor", "reason:EXECUTOR_MISSING")
    assert "4 of the last 6" in first[0].rationale
    assert "STATIC_VALIDATION_FAILED:SyntaxError" in first[1].rationale
    assert all(c.packet is None for c in first)  # never directly executable
    # A one-off defect is not a repair; fingerprints are stable across cycles.
    assert [c.fingerprint for c in observer.observe({})] == [
        c.fingerprint for c in first
    ]


@needs_brain
def test_health_observer_proposals_flow_through_the_loop_gate(factory, tmp_path):
    from calyx_brain.autonomy_loop import run_cycle
    from calyx_brain.autonomy_pulse import PulseLedger

    with factory() as db:
        for n in range(3):
            _cycle(
                db, n, category="configuration_unavailable", reason="X", healthy=False
            )
        db.commit()
    receipt = run_cycle(
        [CalyxHealthObserver(factory, owner="owner")],
        ledger=PulseLedger(tmp_path / "ledger.json"),
        transport=lambda *a: (500, {}),
        status_transport=lambda *a: (500, {}),
        env={"CALYX_BACKEND_BASE_URL": "http://127.0.0.1:9", "CALYX_API_KEY": "k"},
    )
    assert (receipt["zero_reason"], receipt["detail"]) == (
        "owner_gate",
        "AWAITING_APPROVAL:1",
    )
    assert receipt["submissions"] == []


def test_proposals_summary_is_read_only_and_bounded(factory):
    with factory() as db:
        assert proposals_summary(db) == {
            "total": 0,
            "by_state": {},
            "by_class": {},
            "pending": [],
        }
        state = {
            "schema": "brain-calyx-autonomy-ledger.v1",
            "work": {},
            "loop": {
                "proposals": {
                    f"f{i}": {
                        "fingerprint": f"f{i}",
                        "work_class": "engineering_development",
                        "origin": "engineering_objectives",
                        "state": "awaiting_approval",
                        "rationale": f"objective {i}",
                        "first_seen": f"2026-10-13T00:00:0{i}+00:00",
                        "last_seen": "2026-10-13T01:00:00+00:00",
                    }
                    for i in range(3)
                }
            },
        }
        db.add(CalyxBrainPulseLedger(ledger_key="loop", state_json=json.dumps(state)))
        db.commit()
        summary = proposals_summary(db, limit=2)
    assert summary["total"] == 3
    assert summary["by_state"] == {"awaiting_approval": 3}
    assert [p["fingerprint"] for p in summary["pending"]] == ["f0", "f1"]
    assert "OC_BRAIN_LOOP_APPROVALS" in summary["how_to_approve"]


def test_proposals_summary_tolerates_a_database_without_ledgers():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with Session(engine) as db:
        assert proposals_summary(db) is None
