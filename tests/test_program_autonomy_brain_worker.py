"""The deployable Brain-pulse worker entrypoint fails closed on configuration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from runtime.program_autonomy_brain_worker import build_worker, configuration_problems

REPO_ROOT = Path(__file__).resolve().parents[1]
BRAIN = os.environ.get("OC_BRAIN_REPO_PATH", "").strip()


def test_every_missing_setting_is_named():
    assert configuration_problems({}) == [
        "OC_BRAIN_CHECKOUT_UNSET",
        "OC_BRAIN_PULSE_LEDGER_UNSET",
        "CALYX_BACKEND_BASE_URL_UNSET",
        "CALYX_API_KEY_UNSET",
        "OC_BRAIN_WORK_MANIFEST_OR_SOURCES_UNSET",
    ]


def test_work_sources_and_limits_are_validated(tmp_path):
    checkout = tmp_path / "brain"
    (checkout / "calyx_brain").mkdir(parents=True)
    (checkout / "calyx_brain" / "autonomy_pulse.py").write_text("")
    env = {
        "OC_BRAIN_CHECKOUT": str(checkout),
        "OC_BRAIN_PULSE_LEDGER": "database:acceptance",
        "CALYX_BACKEND_BASE_URL": "http://127.0.0.1:8000",
        "CALYX_API_KEY": "fixture",
        "OC_BRAIN_WORK_SOURCES": "traitbank_intake",
        "OC_BRAIN_PULSE_MAX_SUBMISSIONS_PER_DAY": "0",
        "OC_BRAIN_PULSE_MAX_IN_FLIGHT_PER_SOURCE": "two",
    }
    # Sources need a Brain checkout that provides work_sources; limits are bounded.
    assert configuration_problems(env) == [
        "OC_BRAIN_CHECKOUT_MISSING_WORK_SOURCES",
        "OC_BRAIN_PULSE_MAX_SUBMISSIONS_PER_DAY_OUT_OF_RANGE",
        "OC_BRAIN_PULSE_MAX_IN_FLIGHT_PER_SOURCE_OUT_OF_RANGE",
    ]
    (checkout / "calyx_brain" / "work_sources.py").write_text("")
    env["OC_BRAIN_PULSE_MAX_SUBMISSIONS_PER_DAY"] = "200"
    env["OC_BRAIN_PULSE_MAX_IN_FLIGHT_PER_SOURCE"] = "2"
    assert configuration_problems(env) == []


def test_wrong_paths_are_rejected_before_any_loop(tmp_path):
    env = {
        "OC_BRAIN_CHECKOUT": str(tmp_path),
        "OC_BRAIN_WORK_MANIFEST": str(tmp_path / "missing.json"),
        "OC_BRAIN_PULSE_LEDGER": str(tmp_path / "ledger.json"),
        "CALYX_BACKEND_BASE_URL": "http://127.0.0.1:9",
        "CALYX_API_KEY": "fixture",
    }
    assert configuration_problems(env) == [
        "OC_BRAIN_CHECKOUT_MISSING_AUTONOMY_PULSE",
        "OC_BRAIN_WORK_MANIFEST_NOT_FOUND",
    ]
    with pytest.raises(ValueError, match="OC_BRAIN_CHECKOUT_MISSING_AUTONOMY_PULSE"):
        build_worker(env)


def test_unconfigured_entrypoint_reports_configuration_unavailable_and_exits():
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("OC_BRAIN_", "CALYX_"))
    }
    env["PYTHONPATH"] = str(REPO_ROOT)
    completed = subprocess.run(
        [sys.executable, "-m", "runtime.program_autonomy_brain_worker"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    record = json.loads(completed.stdout.strip().splitlines()[-1])
    assert record["started"] is False
    assert record["zero_reason"] == "configuration_unavailable"
    assert "CALYX_API_KEY_UNSET" in record["detail"]


@pytest.mark.skipif(
    not BRAIN or not (Path(BRAIN) / "calyx_brain" / "autonomy_pulse.py").is_file(),
    reason="OC_BRAIN_REPO_PATH must name a Brain checkout with autonomy_pulse.py",
)
def test_disabled_policy_never_builds_a_worker(tmp_path):
    manifest = tmp_path / "work.json"
    manifest.write_text(json.dumps({"work": []}))
    env = {
        "OC_BRAIN_CHECKOUT": BRAIN,
        "OC_BRAIN_WORK_MANIFEST": str(manifest),
        "OC_BRAIN_PULSE_LEDGER": str(tmp_path / "ledger.json"),
        "CALYX_BACKEND_BASE_URL": "http://127.0.0.1:9",
        "CALYX_API_KEY": "fixture",
        "CALYX_PROGRAM_AUTONOMY_ENABLED": "false",
    }
    with pytest.raises(PermissionError, match="PROGRAM_AUTONOMY_NOT_AUTHORIZED"):
        build_worker(env)
    with pytest.raises(ValueError, match="BACKOFF_OUT_OF_RANGE"):
        build_worker(
            {
                **env,
                "CALYX_PROGRAM_AUTONOMY_ENABLED": "true",
                "CALYX_PROGRAM_AUTONOMY_OWNER": "backend_api_key",
                "OC_BRAIN_PULSE_BACKOFF_BASE_SECONDS": "0",
            }
        )


@pytest.mark.skipif(
    not BRAIN or not (Path(BRAIN) / "calyx_brain" / "work_sources.py").is_file(),
    reason="OC_BRAIN_REPO_PATH must name a Brain checkout with work_sources.py",
)
def test_sources_worker_refreshes_its_workspace_and_discovers_new_commits(tmp_path):
    """Wiring: the replenish step refreshes the clone, then discovers from it."""

    def git(repo, *args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    origin = tmp_path / "origin"
    (origin / "data" / "traitbank").mkdir(parents=True)
    git(origin, "init", "-q", "-b", "source")
    (origin / "data" / "traitbank" / "a.json").write_text('{"batch_key": "a"}')
    git(origin, "add", "-A")
    git(
        origin,
        "-c",
        "user.email=t@e.invalid",
        "-c",
        "user.name=t",
        "commit",
        "-qm",
        "a",
    )
    workspace = tmp_path / "workspace"
    subprocess.run(
        [
            "git",
            "clone",
            "-q",
            "--depth",
            "1",
            "--branch",
            "source",
            f"file://{origin}",
            str(workspace),
        ],
        check=True,
    )
    worker = build_worker(
        {
            "OC_BRAIN_CHECKOUT": BRAIN,
            "OC_BRAIN_WORK_SOURCES": "traitbank_intake",
            "OC_BRAIN_PULSE_LEDGER": str(tmp_path / "ledger.json"),
            # Nothing listens here: submissions fail and back off, which is
            # fine; this test is about discovery, not delivery.
            "CALYX_BACKEND_BASE_URL": "http://127.0.0.1:9",
            "CALYX_API_KEY": "fixture",
            "CALYX_PROGRAM_AUTONOMY_ENABLED": "true",
            "CALYX_PROGRAM_AUTONOMY_OWNER": "backend_api_key",
            "CALYX_PROGRAM_AUTONOMY_WORKSPACE": str(workspace),
            "GITHUB_REPOSITORY": "jsp1440/orchid-calyx-backend",
            "OC_BRAIN_WORKSPACE_REFRESH_SECONDS": "60",
            "OC_BRAIN_WORKSPACE_REFRESH_REF": "source",
        }
    )
    first = worker.replenish()
    assert first["workspace_refresh"]["status"] == "current"
    assert first["sources"][0]["discovered"] == 1

    (origin / "data" / "traitbank" / "b.json").write_text('{"batch_key": "b"}')
    git(origin, "add", "-A")
    git(
        origin,
        "-c",
        "user.email=t@e.invalid",
        "-c",
        "user.name=t",
        "commit",
        "-qm",
        "b",
    )
    # Within the interval the clone is not touched.
    assert worker.replenish()["workspace_refresh"] == {"status": "not_due"}


def test_loop_mode_configuration_is_validated(tmp_path):
    checkout = tmp_path / "brain"
    (checkout / "calyx_brain").mkdir(parents=True)
    (checkout / "calyx_brain" / "autonomy_pulse.py").write_text("")
    env = {
        "OC_BRAIN_CHECKOUT": str(checkout),
        "OC_BRAIN_PULSE_LEDGER": "database:loop",
        "CALYX_BACKEND_BASE_URL": "http://127.0.0.1:8000",
        "CALYX_API_KEY": "fixture",
        "OC_BRAIN_LOOP_OBSERVERS": "completion_feedback",
    }
    assert configuration_problems(env) == ["OC_BRAIN_CHECKOUT_MISSING_AUTONOMY_LOOP"]
    (checkout / "calyx_brain" / "autonomy_loop.py").write_text("")
    assert configuration_problems(env) == []
    no_loop = {k: v for k, v in env.items() if k != "OC_BRAIN_LOOP_OBSERVERS"}
    no_loop["OC_BRAIN_WORK_SOURCES"] = "traitbank_intake"
    (checkout / "calyx_brain" / "work_sources.py").write_text("")
    assert configuration_problems(
        {**no_loop, "OC_BRAIN_LOOP_APPROVALS": str(tmp_path / "a.json")}
    ) == ["OC_BRAIN_LOOP_APPROVALS_REQUIRES_LOOP_OBSERVERS"]


@pytest.mark.skipif(
    not BRAIN or not (Path(BRAIN) / "calyx_brain" / "autonomy_loop.py").is_file(),
    reason="OC_BRAIN_REPO_PATH must name a Brain checkout with autonomy_loop.py",
)
def test_loop_mode_worker_reports_an_explicit_cause_when_nothing_runs(tmp_path):
    queue = tmp_path / "queue.json"
    queue.write_text(
        json.dumps(
            {
                "schema": "oc.autonomy-mission-queue.v1",
                "lanes": [
                    {"id": "atlas", "missions": [{"id": "A-1", "objective": "x"}]}
                ],
            }
        )
    )
    worker = build_worker(
        {
            "OC_BRAIN_CHECKOUT": BRAIN,
            "OC_BRAIN_LOOP_OBSERVERS": f"completion_feedback,engineering_objectives:{queue}",
            "OC_BRAIN_PULSE_LEDGER": str(tmp_path / "ledger.json"),
            "CALYX_BACKEND_BASE_URL": "http://127.0.0.1:9",
            "CALYX_API_KEY": "fixture",
            "CALYX_PROGRAM_AUTONOMY_ENABLED": "true",
            "CALYX_PROGRAM_AUTONOMY_OWNER": "backend_api_key",
        }
    )
    record = worker.replenish()
    assert (record["zero_reason"], record["detail"]) == (
        "owner_gate",
        "AWAITING_APPROVAL:1",
    )
    assert record["loop"]["generated"] == {"engineering_development": 1}
    # The cycle records the paid coding lane's gate (NO_API_MODE unset: blocked),
    # and the durable receipt summary keeps it.
    assert record["coding_lane"] == {"state": "provider_blocked", "gate": "no-api-mode"}
    from app.calyx_orchestrator.autonomy_cycles import _replenishment_summary

    assert _replenishment_summary(record)["coding_lane"] == record["coding_lane"]


@pytest.mark.skipif(
    not BRAIN or not (Path(BRAIN) / "calyx_brain" / "autonomy_loop.py").is_file(),
    reason="OC_BRAIN_REPO_PATH must name a Brain checkout with autonomy_loop.py",
)
def test_calyx_health_observer_is_wired_from_the_loop_spec(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import database
    from app.calyx_orchestrator.program_models import (
        CalyxAutonomyCycle,
        CalyxProgram,
        CalyxProgramJob,
    )

    engine = create_engine(f"sqlite:///{tmp_path / 'calyx.db'}")
    database.Base.metadata.create_all(
        engine,
        tables=[
            CalyxAutonomyCycle.__table__,
            CalyxProgram.__table__,
            CalyxProgramJob.__table__,
        ],
    )
    factory = sessionmaker(engine)
    with factory() as db:
        for n in range(3):
            db.add(
                CalyxAutonomyCycle(
                    owner="backend_api_key",
                    worker_id="w",
                    sequence=n,
                    poll_seconds=30,
                    finished_at=datetime(2026, 10, 13, tzinfo=UTC)
                    + timedelta(seconds=n),
                    productive=False,
                    healthy=False,
                    category="no_executor",
                    reason_code="AUTHORITATIVE_EXECUTOR_NOT_REGISTERED",
                )
            )
        db.commit()
    monkeypatch.setattr(database, "get_session_local", lambda: factory)
    worker = build_worker(
        {
            "OC_BRAIN_CHECKOUT": BRAIN,
            "OC_BRAIN_LOOP_OBSERVERS": "calyx_health",
            "OC_BRAIN_PULSE_LEDGER": str(tmp_path / "ledger.json"),
            "CALYX_BACKEND_BASE_URL": "http://127.0.0.1:9",
            "CALYX_API_KEY": "fixture",
            "CALYX_PROGRAM_AUTONOMY_ENABLED": "true",
            "CALYX_PROGRAM_AUTONOMY_OWNER": "backend_api_key",
        }
    )
    record = worker.replenish()
    assert record["loop"]["observers"] == [
        {"name": "calyx_health", "status": "ok", "gaps": 1}
    ]
    assert (record["zero_reason"], record["detail"]) == (
        "owner_gate",
        "AWAITING_APPROVAL:1",
    )
