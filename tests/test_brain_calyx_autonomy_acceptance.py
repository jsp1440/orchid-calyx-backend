"""Cross-repository Brain -> Calyx autonomy acceptance and recovery.

These tests use the real Brain caller and pulse from an Orchid-Continuum-Brain
checkout (``OC_BRAIN_REPO_PATH``), the real canonical submit route and program
route with real ``CALYX_API_KEY`` authentication (no dependency overrides), a
disposable PostgreSQL schema and the registered read-only executors.

They skip with an explicit reason when no Brain checkout is configured: this
repository's CI does not check out the Brain repository. The PostgreSQL gate is
the shared ``requires_postgres`` marker.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.calyx_orchestrator.execution_bridge import LeaseExecutionBridge
from app.calyx_orchestrator.executor_registry import AuthoritativeExecutorRegistry
from app.calyx_orchestrator.program_cycle import run_deterministic_program_cycle
from app.calyx_orchestrator.program_models import CalyxProgram, CalyxProgramJob
from app.calyx_orchestrator.program_routes import router as program_router
from app.calyx_orchestrator.program_worker import PersistentProgramWorker
from app.calyx_orchestrator.schema import ensure_orchestrator_schema
from app.canonical_brain.api import create_brain_router
from app.database import get_db

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "oc_brain_calyx_autonomy_acceptance.py"
BRAIN = os.environ.get("OC_BRAIN_REPO_PATH", "").strip()
REPOSITORY = "jsp1440/orchid-calyx-backend"
BRANCH = "autonomy/brain-calyx-recovery"
API_KEY = "fixture-" + uuid.uuid4().hex
OWNER = "backend_api_key"

pytestmark = [
    pytest.mark.requires_postgres("TEST_DATABASE_URL"),
    pytest.mark.skipif(
        not BRAIN or not (Path(BRAIN) / "calyx_brain" / "autonomy_pulse.py").is_file(),
        reason="OC_BRAIN_REPO_PATH must name an Orchid-Continuum-Brain checkout "
        "containing calyx_brain/autonomy_pulse.py",
    ),
]


def _brain():
    if BRAIN not in sys.path:
        sys.path.append(BRAIN)
    from calyx_brain import autonomy_pulse, canonical_handoff, reasoning_contracts

    return autonomy_pulse, canonical_handoff, reasoning_contracts


def _guard_dsn(dsn: str) -> None:
    url = urlsplit(dsn)
    assert url.scheme == "postgresql"
    assert (
        url.username == "oc_local"
        and url.hostname == "127.0.0.1"
        and url.port is not None
        and url.path == "/postgres"
    ) or (
        url.username == "ocvalidate"
        and url.hostname == "localhost"
        and url.port == 5432
        and url.path == "/oc_validate"
    )


def test_ten_consecutive_productive_scheduled_cycles_with_recovery(tmp_path):
    """Runs the full timer-driven acceptance harness and checks its report."""
    dsn = os.environ["TEST_DATABASE_URL"]
    _guard_dsn(dsn)
    output = tmp_path / "acceptance.json"
    env = {key: value for key, value in os.environ.items() if key != "PGHOST"}
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            str(SCRIPT),
            "--dsn",
            dsn,
            "--brain-repo",
            BRAIN,
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    assert output.exists(), completed.stderr[-4000:]
    report = json.loads(output.read_text())
    failed = [a for a in report["assertions"] if not a["passed"]]
    assert report["passed"] and not failed, json.dumps(failed, indent=1)[:6000]
    cycles = report["phase_a"]["cycles"]
    assert len(cycles) == 10
    assert all(cycle["classification"]["productive"] for cycle in cycles)
    assert report["phase_b"]["recovery_cycle_categories"].get("no_eligible_work")


# ---------------------------------------------------------------------------
# In-process recovery scenarios over the real routes and authentication
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    dsn = os.environ["TEST_DATABASE_URL"]
    _guard_dsn(dsn)
    schema = "bc_recovery_" + uuid.uuid4().hex
    admin = create_engine(dsn)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    local = create_engine(dsn, connect_args={"options": f"-csearch_path={schema}"})
    with Session(local) as db:
        ensure_orchestrator_schema(db)
    try:
        yield local
    finally:
        local.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def source(tmp_path):
    repo = tmp_path / "source"
    (repo / "app").mkdir(parents=True)
    for command in (
        ["init", "-q", "-b", BRANCH],
        ["config", "user.email", "test@example.invalid"],
        ["config", "user.name", "Recovery fixture"],
    ):
        subprocess.run(["git", "-C", str(repo), *command], check=True)
    (repo / "AGENTS.md").write_text("fixture\n")
    (repo / "requirements.txt").write_text("")
    (repo / ".calyx-isolated-workspace.json").write_text(
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
    files = []
    for index in range(3):
        path = f"app/recovery_{index}.py"
        body = f"VALUE = {index}\n"
        (repo / path).write_text(body)
        files.append(
            {"path": path, "sha256": hashlib.sha256(body.encode()).hexdigest()}
        )
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
    return repo, files


@pytest.fixture
def api(engine, monkeypatch):
    """Real routers and real API-key authentication; only the DB is redirected."""
    monkeypatch.setenv("CALYX_API_KEY", API_KEY)
    app = FastAPI()
    app.include_router(create_brain_router(prefix="/brain/canonical"))
    app.include_router(program_router, prefix="/brain/orchestrator")

    def db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = db
    client = TestClient(app)

    def post(url, headers, body):
        response = client.post(urlsplit(url).path, content=body, headers=dict(headers))
        return response.status_code, response.json()

    def get(url, headers):
        response = client.get(urlsplit(url).path, headers=dict(headers))
        return response.status_code, response.json()

    return post, get


ENV = {"CALYX_BACKEND_BASE_URL": "http://127.0.0.1:8000", "CALYX_API_KEY": API_KEY}


def _work(files):
    pulse, _, contracts = _brain()
    items = []
    for index, record in enumerate(files):
        candidate = contracts.CandidateKnowledge(
            candidate_id=f"candidate:recovery:{index}",
            subject_id=record["path"],
            predicate="has_verified_repository_source",
            object_id=record["sha256"],
            evidence_ids=(f"fixture:{record['path']}",),
            confidence=0.5,
        )
        packet = contracts.build_verification_program(
            candidate, repository=REPOSITORY, branch=BRANCH, files=[record]
        )
        items.append(pulse.WorkItem(f"work-{index}", packet))
    return items


def _registry(repo, *, drop=None):
    registry = AuthoritativeExecutorRegistry(
        workspace_root=repo, repository_name=REPOSITORY
    )
    if drop:
        del registry._by_role[drop]
    return registry


def _cycle(engine, registry, worker="recovery-worker"):
    with Session(engine) as db:
        return run_deterministic_program_cycle(
            db,
            owner=OWNER,
            worker_id=worker,
            max_jobs=2,
            lease_seconds=60,
            timeout_seconds=30,
            registry=registry,
        )


def test_duplicate_submission_converges_on_one_program_over_real_auth(
    engine, api, source
):
    _, handoff, _ = _brain()
    post, _ = api
    packet = _work(source[1])[0].packet
    first = handoff.submit_canonical_handoff(packet, transport=post, env=ENV)
    replay = handoff.submit_canonical_handoff(packet, transport=post, env=ENV)
    assert (first.outcome, replay.outcome) == ("submitted", "idempotent_replay")
    assert first.program_id == replay.program_id
    wrong = handoff.submit_canonical_handoff(
        packet, transport=post, env={**ENV, "CALYX_API_KEY": "wrong"}
    )
    assert wrong.outcome == "auth_unavailable"
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(CalyxProgram)) == 1
        jobs = db.scalars(
            select(CalyxProgramJob).order_by(CalyxProgramJob.job_key)
        ).all()
        # Dependency ordering: the validator waits for the evidence reader.
        assert [job.status for job in jobs] == ["queued", "waiting"]
        assert {db.get(CalyxProgram, job.program_id).owner for job in jobs} == {OWNER}


def test_missing_executor_is_a_zero_execution_defect_without_a_lease(
    engine, api, source
):
    _, handoff, _ = _brain()
    repo, files = source
    post, _ = api
    handoff.submit_canonical_handoff(_work(files)[0].packet, transport=post, env=ENV)
    result = _cycle(engine, _registry(repo, drop="repository_evidence_reader"))
    assert result.productive_jobs == 0 and result.attempted_jobs == 0
    reason = result.zero_execution
    assert reason["category"] == "no_executor" and reason["healthy"] is False
    assert reason["unregistered_runnable_roles"] == ["repository_evidence_reader"]
    with Session(engine) as db:
        assert all(
            job.lease_token is None and job.attempt_count == 0
            for job in db.scalars(select(CalyxProgramJob))
        )
    # Registering the executor again lets the same queued work run.
    assert _cycle(engine, _registry(repo)).productive_jobs == 2


def test_backend_outage_backs_off_then_the_pulse_recovers(
    engine, api, source, tmp_path
):
    pulse, _, _ = _brain()
    repo, files = source
    post, get = api
    calls = {"n": 0}

    def flaky(url, headers, body):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionResetError("backend restarting")
        return post(url, headers, body)

    ledger = pulse.PulseLedger(tmp_path / "ledger.json")
    work = _work(files)[:1]
    kwargs = {
        "ledger": ledger,
        "transport": flaky,
        "status_transport": get,
        "env": ENV,
        "backoff_base_seconds": 0,
    }
    down = pulse.run_pulse(work, **kwargs)
    assert (
        down["zero_reason"] == "runtime_backoff"
        and not down["submissions"][0]["program_id"]
    )
    up = pulse.run_pulse(work, **kwargs)
    assert up["submissions"][0]["outcome"] == "submitted"
    assert _cycle(engine, _registry(repo)).productive_jobs == 2
    done = pulse.run_pulse(work, **kwargs)
    assert done["reconciled"][0]["state"] == "completed"
    assert done["reconciled"][0]["all_delivered"] is True
    assert done["zero_reason"] == "no_eligible_work"


def test_replayed_completion_is_fenced_and_changes_nothing(engine, api, source):
    _, handoff, _ = _brain()
    repo, files = source
    post, _ = api
    handoff.submit_canonical_handoff(_work(files)[0].packet, transport=post, env=ENV)
    registry = _registry(repo)
    with Session(engine) as db:
        worker = PersistentProgramWorker(db)
        job = worker.claim(
            owner=OWNER,
            worker_id="w1",
            lease_seconds=60,
            allowed_role_keys=registry.eligible_role_keys,
        )
        token, job_id = job.lease_token, job.program_job_id
        from app.calyx_orchestrator.assignment_factory import (
            governed_assignment_from_claimed_job,
        )

        assignment = governed_assignment_from_claimed_job(
            db, owner=OWNER, job=job, timeout_seconds=30
        )
        receipt = registry.require_authoritative(job.role_key).executor.execute(
            assignment
        )
        bridge = LeaseExecutionBridge(db)
        bridge.complete_from_receipt(
            program_job_id=job_id, worker_id="w1", lease_token=token, receipt=receipt
        )
        settled = db.get(CalyxProgramJob, job_id)
        before = (settled.status, settled.outcome, settled.evidence_json)
        with pytest.raises((PermissionError, LookupError, ValueError)):
            bridge.complete_from_receipt(
                program_job_id=job_id,
                worker_id="w1",
                lease_token=token,
                receipt=receipt,
            )
        db.rollback()
        db.expire_all()
        after = db.get(CalyxProgramJob, job_id)
        assert (after.status, after.outcome, after.evidence_json) == before
        assert after.attempt_count == 1


def test_dependency_blocked_work_waits_and_is_not_productive(
    engine, api, source, tmp_path
):
    pulse, _, _ = _brain()
    repo, files = source
    post, get = api
    first, second, _ = _work(files)
    chained = [first, pulse.WorkItem(second.work_id, second.packet, (first.work_id,))]
    ledger = pulse.PulseLedger(tmp_path / "ledger.json")
    kwargs = {
        "ledger": ledger,
        "transport": post,
        "status_transport": get,
        "env": ENV,
        "max_in_flight": 2,
    }
    assert pulse.run_pulse(chained, **kwargs)["submissions"][0]["work_id"] == "work-0"
    blocked = pulse.run_pulse(chained, **kwargs)
    assert blocked["zero_reason"] == "dependency_blocked"
    assert _cycle(engine, _registry(repo)).productive_jobs == 2
    released = pulse.run_pulse(chained, **kwargs)
    assert [s["work_id"] for s in released["submissions"]] == ["work-1"]
