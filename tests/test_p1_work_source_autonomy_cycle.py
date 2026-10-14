"""P1: governed work sources and a durable pulse ledger on the real scheduler.

Runs the real ``run_forever`` loop with the real canonical submit and
orchestrator routes, real API-key auth and disposable PostgreSQL. Work is
*discovered* by Brain's ``TraitBankIntakeSource`` (one item per committed
batch, content-addressed). The pulse ledger is ``DatabasePulseLedger``. The test
proves four things:

1. Discovered scientific work is executed through claim, lease and receipt,
   and a drained queue carries an explicit reason (``WORK_SOURCES_DRAINED``).
2. A restarted worker resumes from the database ledger: nothing is replayed
   or re-executed.
3. New content is discovered and executed exactly once.
4. A broken source yields an unhealthy ``configuration_unavailable`` cycle
   (``WORK_SOURCE_FAILED``), never a healthy idle.
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
from app.calyx_orchestrator.autonomy_cycles import record_cycle
from app.calyx_orchestrator.autonomy_policy import ProgramAutonomyPolicy
from app.calyx_orchestrator.executor_registry import AuthoritativeExecutorRegistry
from app.calyx_orchestrator.program_models import (
    CalyxAutonomyCycle,
    CalyxBrainPulseReceipt,
    CalyxProgramJob,
)
from app.calyx_orchestrator.pulse_ledger_store import DatabasePulseLedger

BRAIN = os.environ.get("OC_BRAIN_REPO_PATH", "").strip()

pytestmark = [
    pytest.mark.requires_postgres("TEST_DATABASE_URL"),
    pytest.mark.skipif(
        not BRAIN or not (Path(BRAIN) / "calyx_brain" / "work_sources.py").is_file(),
        reason="OC_BRAIN_REPO_PATH must name a Brain checkout with "
        "calyx_brain/work_sources.py",
    ),
]


def _brain():
    if BRAIN not in sys.path:
        sys.path.append(BRAIN)
    from calyx_brain import autonomy_pulse, work_sources

    return autonomy_pulse, work_sources


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True)


def _commit_batch(repo: Path, name: str, document: dict) -> None:
    (repo / "data" / "traitbank" / name).write_text(
        json.dumps(document, indent=1, sort_keys=True)
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"add {name}")


@pytest.fixture
def intake_repo(tmp_path):
    repo = tmp_path / "intake"
    (repo / "data" / "traitbank").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", BRANCH)
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "P1 intake fixture")
    (repo / "AGENTS.md").write_text("P1 work-source fixture.\n")
    (repo / "requirements.txt").write_text("")  # required by the evidence reader
    _commit_batch(repo, "darwin_1862.json", _darwin_batch())
    return repo


def _run_cycles(engine, repo, replenish, count):
    registry = AuthoritativeExecutorRegistry(
        workspace_root=repo, repository_name=REPOSITORY
    )
    policy = ProgramAutonomyPolicy(
        enabled=True,
        owner=OWNER,
        worker_id="p1-worker",
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
        )
    finally:
        watchdog.cancel()
    assert len(cycles) == count, "scheduler did not complete the expected cycles"
    return cycles


def test_discovered_work_runs_durably_across_restart_and_replenishes(
    engine, api, intake_repo, monkeypatch
):
    pulse, sources_module = _brain()
    _client, post, get = api
    monkeypatch.setattr(
        worker_module, "get_session_local", lambda: sessionmaker(engine)
    )
    env = {"CALYX_BACKEND_BASE_URL": "http://127.0.0.1:8000", "CALYX_API_KEY": "x"}
    env["CALYX_API_KEY"] = os.environ["CALYX_API_KEY"]  # set by the api fixture
    source = sources_module.TraitBankIntakeSource(intake_repo, REPOSITORY, BRANCH)

    def make_replenish(ledger):
        def replenish():
            items, reports = sources_module.discover_all(
                [source], ledger_state=ledger.load()
            )
            return pulse.run_pulse(
                items,
                ledger=ledger,
                transport=post,
                status_transport=get,
                env=env,
                source_reports=reports,
                max_submissions_per_day=50,
            )

        return replenish

    def ledger():
        return DatabasePulseLedger(
            sessionmaker(engine), key="p1-intake", ledger_schema=pulse.LEDGER_SCHEMA
        )

    # Worker session 1: discover the Darwin batch, execute it, drain.
    first, drained = _run_cycles(engine, intake_repo, make_replenish(ledger()), 2)
    assert [s["outcome"] for s in first["replenishment"]["submissions"]] == [
        "submitted"
    ]
    assert first["replenishment"]["submissions"][0]["work_id"].startswith(
        "traitbank:data/traitbank/darwin_1862.json@"
    )
    assert first["classification"]["productive"] is True, json.dumps(
        {k: first.get(k) for k in ("classification", "cycle")}, default=str
    )[:3000]
    assert [j["executor_key"] for j in first["cycle"]["jobs"]] == [
        "repository_evidence_reader_v1",
        "traitbank_batch_validator_v1",
    ]
    assert (
        drained["replenishment"]["zero_reason"],
        drained["replenishment"]["detail"],
    ) == ("no_eligible_work", "WORK_SOURCES_DRAINED")
    assert drained["classification"] == {
        "productive": False,
        "category": "no_eligible_work",
        "healthy": True,
    }

    # New scientific content arrives while the worker is down.
    probe = _darwin_batch()
    probe["batch_key"] += "-second-batch"
    _commit_batch(intake_repo, "darwin_1862_second.json", probe)

    # Worker session 2 (a restart: a fresh ledger object over the same rows).
    resumed, drained_again = _run_cycles(
        engine, intake_repo, make_replenish(ledger()), 2
    )
    submissions = resumed["replenishment"]["submissions"]
    # Only the new batch is submitted; the finished one is not replayed.
    assert [(s["outcome"], s["work_id"].split("@")[0]) for s in submissions] == [
        ("submitted", "traitbank:data/traitbank/darwin_1862_second.json")
    ]
    assert resumed["classification"]["productive"] is True
    assert drained_again["replenishment"]["detail"] == "WORK_SOURCES_DRAINED"

    with Session(engine) as db:
        jobs = db.scalars(select(CalyxProgramJob)).all()
        assert len(jobs) == 4 and len({j.job_key for j in jobs}) == 4
        assert {(j.status, j.outcome, j.attempt_count) for j in jobs} == {
            ("completed", "DELIVERED", 1)
        }
        pulse_receipts = db.scalars(select(CalyxBrainPulseReceipt)).all()
        assert len(pulse_receipts) == 4  # durable, one per pulse
        replays = [
            s
            for r in pulse_receipts
            for s in json.loads(r.receipt_json)["submissions"]
            if s["outcome"] == "idempotent_replay"
        ]
        assert replays == []
        cycles = db.scalars(
            select(CalyxAutonomyCycle).order_by(CalyxAutonomyCycle.finished_at)
        ).all()
        summaries = [json.loads(c.replenishment_json) for c in cycles]
        assert all(s["sources"][0]["name"] == "traitbank_intake" for s in summaries)
        assert [c.productive for c in cycles] == [True, False, True, False]


def test_broken_source_is_an_unhealthy_cycle_not_an_idle(
    engine, api, intake_repo, monkeypatch, tmp_path
):
    pulse, sources_module = _brain()
    _client, post, get = api
    monkeypatch.setattr(
        worker_module, "get_session_local", lambda: sessionmaker(engine)
    )
    env = {
        "CALYX_BACKEND_BASE_URL": "http://127.0.0.1:8000",
        "CALYX_API_KEY": os.environ["CALYX_API_KEY"],
    }
    broken = sources_module.TraitBankIntakeSource(
        tmp_path / "missing", REPOSITORY, BRANCH
    )
    ledger = DatabasePulseLedger(
        sessionmaker(engine), key="p1-broken", ledger_schema=pulse.LEDGER_SCHEMA
    )

    def replenish():
        items, reports = sources_module.discover_all(
            [broken], ledger_state=ledger.load()
        )
        return pulse.run_pulse(
            items,
            ledger=ledger,
            transport=post,
            status_transport=get,
            env=env,
            source_reports=reports,
        )

    (cycle,) = _run_cycles(engine, intake_repo, replenish, 1)
    assert cycle["replenishment"]["zero_reason"] == "configuration_unavailable"
    assert cycle["replenishment"]["detail"] == "WORK_SOURCE_FAILED:traitbank_intake"
    assert cycle["classification"] == {
        "productive": False,
        "category": "configuration_unavailable",
        "healthy": False,
    }
