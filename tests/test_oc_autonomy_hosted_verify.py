"""The hosted verifier accepts real-world pasted DSNs and never echoes them."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

REPO_ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "oc_autonomy_hosted_verify",
        REPO_ROOT / "scripts" / "oc_autonomy_hosted_verify.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOST = "ep-x-123.us-west-2.aws.neon.tech"
PLAIN = f"postgresql://oc_verify:s3cret@{HOST}/neondb?sslmode=require"


@pytest.mark.parametrize(
    "raw",
    [
        PLAIN,
        f"  {PLAIN}\n",
        f"'{PLAIN}'",
        f"psql '{PLAIN}'",
        PLAIN.replace("postgresql://", "postgres://"),
    ],
)
def test_pasted_forms_normalize_to_a_parseable_url(raw):
    url = make_url(_module().normalize_dsn(raw))
    assert (url.drivername, url.username, url.password) == (
        "postgresql",
        "oc_verify",
        "s3cret",
    )
    assert (url.host, url.database, url.query["sslmode"]) == (
        HOST,
        "neondb",
        "require",
    )


def test_reserved_characters_in_the_password_are_encoded():
    raw = f"postgresql://oc_verify:p@ss#w/rd?x:y@{HOST}/neondb?sslmode=require"
    url = make_url(_module().normalize_dsn(raw))
    assert url.password == "p@ss#w/rd?x:y"
    assert url.host == HOST and url.database == "neondb"


def test_already_encoded_password_is_not_double_encoded():
    raw = f"postgresql://oc_verify:p%40ss@{HOST}/neondb"
    assert make_url(_module().normalize_dsn(raw)).password == "p@ss"


def test_unparseable_dsn_reports_shape_not_value(capsys, monkeypatch):
    module = _module()
    monkeypatch.setattr(
        "sys.argv", ["verify", "--dsn", "not a url with secret-value-123"]
    )
    assert module.main() == 1
    out = capsys.readouterr().out
    assert "VERIFY_DSN_UNPARSEABLE" in out
    assert "secret-value-123" not in out


# --- Mid-run restart evidence: leases, receipts, persistence ----------------

OWNER = "acceptance-owner"


def _seed(tmp_path, *, rerun_after_restart=False, leftover_lease=False):
    """Two worker sessions; the restart happens while work is still queued."""
    import json
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.calyx_orchestrator.program_models import (
        CalyxAutonomyCycle,
        CalyxProgram,
        CalyxProgramJob,
    )
    from app.calyx_orchestrator.schema import ensure_orchestrator_schema

    engine = create_engine(f"sqlite:///{tmp_path / 'midrun.db'}")
    db = Session(engine)
    ensure_orchestrator_schema(db)
    start = datetime.now(UTC) - timedelta(minutes=5)
    # Session 1 executes w0..w2; session 2 replays them and executes w3..w4.
    plan = [
        (1, ["job-w0"]),
        (2, ["job-w1"]),
        (3, ["job-w2"]),
        (1, ["job-w2"] if rerun_after_restart else []),
        (2, ["job-w3"]),
        (3, ["job-w4"]),
        (4, []),
        (5, []),
    ]
    for index in range(5):
        db.add(
            CalyxProgram(
                program_id=f"p{index}",
                owner=OWNER,
                title="t",
                objective="o",
                status="completed",
                created_at=start + timedelta(seconds=index),
            )
        )
        db.add(
            CalyxProgramJob(
                program_job_id=f"j{index}",
                program_id=f"p{index}",
                job_key=f"job-w{index}",
                role_key="repository_verifier",
                title="t",
                repository="r",
                work_fingerprint=f"f{index}",
                status="completed",
                outcome="DELIVERED",
                attempt_count=1,
                lease_owner="worker" if leftover_lease and index == 4 else None,
                evidence_json=json.dumps(
                    {
                        "receipt_type": "execution",
                        "executor_key": "ex_v1",
                        "state": "delivered",
                        "input_checksum": f"in{index}",
                        "output_checksum": f"out{index}",
                        "output": {"big": "payload"},
                    }
                ),
                created_at=start + timedelta(seconds=index),
            )
        )
    for position, (sequence, keys) in enumerate(plan):
        replays = (
            [{"work_id": f"w{n}", "outcome": "idempotent_replay"} for n in range(3)]
            if position == 3
            else []
        )
        drained = position >= 6
        db.add(
            CalyxAutonomyCycle(
                cycle_id=f"c{position}",
                owner=OWNER,
                worker_id="worker",
                sequence=sequence,
                poll_seconds=30,
                started_at=start + timedelta(seconds=30 * position),
                finished_at=start + timedelta(seconds=30 * position + 5)
                if position < 7
                else datetime.now(UTC),
                productive=bool(keys),
                healthy=True,
                category=None if keys else "no_eligible_work",
                productive_jobs=len(keys),
                job_keys_json=json.dumps(keys),
                replenishment_json=json.dumps(
                    {
                        "zero_reason": "no_eligible_work" if drained else None,
                        "submitted": replays,
                    }
                ),
            )
        )
    db.commit()
    return db


def test_midrun_restart_proves_persistence_and_released_leases(tmp_path):
    module = _module()
    db = _seed(tmp_path)
    report = module.verify(db, owner=OWNER, min_consecutive=3, require_midrun=True)
    checks = report["checks"]
    assert checks["no_outstanding_leases"] == {"passed": True, "held_or_running": []}
    assert checks["persistent_state_across_restart"] == {
        "passed": True,
        "jobs_executed_before_restart": 3,
        "jobs_executed_after_restart": 2,
        "executed_on_both_sides": [],
    }
    assert checks["resumed_after_midrun_restart"]["passed"] is True

    records = module.export_records(db, owner=OWNER)
    assert records["schema"] == "oc-autonomy-hosted-records.v2"
    assert [p["program_id"] for p in records["programs"]] == [f"p{i}" for i in range(5)]
    job = records["jobs"][3]
    assert job["executed_in_cycle_id"] == "c4" and job["lease_owner"] is None
    assert job["receipt"] == {
        "receipt_type": "execution",
        "executor_key": "ex_v1",
        "state": "delivered",
        "input_checksum": "in3",
        "output_checksum": "out3",
    }
    # Executor payloads and lease tokens never leave the database.
    exported = str(records)
    assert "payload" not in exported and "lease_token" not in exported
    assert records["cycles"][0]["job_keys"] == ["job-w0"]


def test_reexecution_across_restart_and_held_leases_fail(tmp_path):
    module = _module()
    db = _seed(tmp_path, rerun_after_restart=True, leftover_lease=True)
    checks = module.verify(db, owner=OWNER, min_consecutive=3, require_midrun=True)[
        "checks"
    ]
    assert checks["persistent_state_across_restart"]["executed_on_both_sides"] == [
        "job-w2"
    ]
    assert checks["persistent_state_across_restart"]["passed"] is False
    assert checks["no_outstanding_leases"] == {
        "passed": False,
        "held_or_running": ["job-w4"],
    }


def test_database_override_rejects_unsafe_names(capsys, monkeypatch):
    module = _module()
    monkeypatch.setattr(
        "sys.argv", ["verify", "--dsn", PLAIN, "--database", "x; DROP TABLE y"]
    )
    assert module.main() == 1
    assert "VERIFY_DATABASE_NAME_INVALID" in capsys.readouterr().out


@pytest.mark.requires_postgres("TEST_DATABASE_URL")
def test_database_override_verifies_the_named_database(capsys, monkeypatch):
    """The mid-run label reuses the first run's role on autonomy_midrun."""
    import json
    import os

    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from app.calyx_orchestrator.schema import ensure_orchestrator_schema

    dsn = os.environ["TEST_DATABASE_URL"]
    engine = create_engine(dsn)
    with engine.connect() as connection:
        name = connection.execute(text("SELECT current_database()")).scalar_one()
    # The verifier reads the Calyx tables; a fresh test database has none yet.
    with Session(engine) as db:
        ensure_orchestrator_schema(db)
    engine.dispose()
    elsewhere = str(make_url(dsn).set(database="postgres").render_as_string(False))
    monkeypatch.setattr("sys.argv", ["verify", "--dsn", elsewhere, "--database", name])
    _module().main()
    report = json.loads(capsys.readouterr().out)
    assert report["environment"]["database"] == name
