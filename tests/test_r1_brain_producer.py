"""Authenticated canonical producer against disposable PostgreSQL."""

import json
import os
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.calyx_orchestrator.executor_registry import AuthoritativeExecutorRegistry
from app.calyx_orchestrator.program_cycle import run_deterministic_program_cycle
from app.calyx_orchestrator.program_models import CalyxProgram, CalyxProgramJob
from app.calyx_orchestrator.program_worker import PersistentProgramWorker
from app.calyx_orchestrator.schema import ensure_orchestrator_schema
from app.canonical_brain.api import create_brain_router
from app.database import get_db
from app.security import verify_owner_or_api_key


@pytest.fixture
def engine():
    dsn = os.environ["TEST_DATABASE_URL"]
    test_url = urlsplit(dsn)
    assert test_url.scheme == "postgresql"
    assert (
        test_url.username == "oc_local"
        and test_url.hostname == "127.0.0.1"
        and test_url.port is not None
        and test_url.path == "/postgres"
    ) or (
        test_url.username == "ocvalidate"
        and test_url.hostname == "localhost"
        and test_url.port == 5432
        and test_url.path == "/oc_validate"
    )
    schema = "r1_producer_" + uuid.uuid4().hex
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


def client(engine, owner="r1-owner"):
    app = FastAPI()
    app.include_router(create_brain_router())

    def db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = db
    if owner is not None:
        app.dependency_overrides[verify_owner_or_api_key] = lambda: {"subject": owner}
    return TestClient(app)


def payload(keys=("R1-BUILD-A",), *, role="repository_evidence_reader", root=None):
    return {
        "schema_version": "canonical-brain-program-handoff.v1",
        "admissions": [
            {
                "build_id": key,
                "architecture_id": "architecture:brain",
                "intent_ids": ["intent:r1"],
                "decision_ids": ["decision:r1"],
                "source_uris": ["brain://r1/source"],
                "validation_plan_ids": ["validation:r1"],
                "deterministic_outputs": True,
                "preserves_provenance": True,
                "separates_evidence_from_inference": True,
            }
            for key in keys
        ],
        "metadata": [
            {
                "build_id": key,
                "role_key": role,
                "repository": "jsp1440/orchid-calyx-backend",
                "branch": "autonomy/r1-producer",
            }
            for key in keys
        ],
        "dependencies": [[keys[i], keys[i + 1]] for i in range(len(keys) - 1)],
        "inputs": {key: {"repository_root": str(root)} if root else {} for key in keys},
    }


def post(c, body):
    return c.post("/brain/canonical/builds/submit", json=body)


def test_authentication_owner_spoof_and_protocol_rejection_do_not_write(engine):
    body = payload()
    assert post(client(engine, None), body).status_code == 401
    assert post(client(engine), {**body, "owner": "victim"}).status_code == 422
    assert (
        post(client(engine), {**body, "schema_version": "unknown.v9"}).status_code
        == 422
    )
    assert post(client(engine, ""), body).status_code == 401
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(CalyxProgram)) == 0


@pytest.mark.parametrize(
    "failure", ["role", "test_executor", "admission", "dependency"]
)
def test_real_producer_rejects_unsupported_work_before_persistence(engine, failure):
    body = payload()
    if failure == "role":
        body["metadata"][0]["role_key"] = "brain_engineer"
    elif failure == "test_executor":
        body["metadata"][0]["role_key"] = "autonomy_probe"
    elif failure == "admission":
        body["admissions"][0]["merge_requested"] = True
    else:
        body["dependencies"] = [["missing-build", "R1-BUILD-A"]]
    result = post(client(engine), body)
    assert result.status_code == 409, result.text
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(CalyxProgramJob)) == 0


def test_partial_batch_overlap_is_rejected_and_owners_remain_separate(engine):
    c = client(engine)
    first = post(c, payload())
    assert first.status_code == 200, first.text
    assert post(c, payload(("R1-BUILD-A", "R1-BUILD-B"))).status_code == 409
    other = post(client(engine, "other-owner"), payload())
    assert (
        other.status_code == 200
        and other.json()["program_id"] != first.json()["program_id"]
    )


def test_competing_authenticated_producers_converge_to_one_owned_program(engine):
    barrier = threading.Barrier(2)

    def produce(_):
        c = client(engine)
        barrier.wait(timeout=10)
        response = post(c, payload())
        assert response.status_code == 200, response.text
        return response.json()["program_id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(produce, range(2)))
    assert ids[0] == ids[1]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(CalyxProgramJob)) == 1


def test_authenticated_intake_reaches_real_executor_completion_and_dependency_release(
    engine, tmp_path, monkeypatch
):
    renewals = []
    heartbeat = PersistentProgramWorker.heartbeat

    def record_heartbeat(self, **kwargs):
        renewals.append(kwargs["lease_seconds"])
        return heartbeat(self, **kwargs)

    monkeypatch.setattr(PersistentProgramWorker, "heartbeat", record_heartbeat)
    repo = tmp_path / "source"
    repo.mkdir()
    for command in (
        ["init", "-b", "autonomy/r1-producer"],
        ["config", "user.email", "test@example.invalid"],
        ["config", "user.name", "R1 isolated test"],
    ):
        subprocess.run(
            ["git", "-C", str(repo), *command], check=True, capture_output=True
        )
    (repo / "AGENTS.md").write_text("Provider-free source verification fixture.\n")
    (repo / "requirements.txt").write_text("")
    subprocess.run(
        ["git", "-C", str(repo), "add", "AGENTS.md", "requirements.txt"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "isolated source"], check=True
    )
    body = payload(("R1-BUILD-A", "R1-BUILD-B"), root=repo)
    c = client(engine)
    response = post(c, body)
    assert response.status_code == 200, response.text
    with Session(engine) as db:
        jobs = db.scalars(
            select(CalyxProgramJob).order_by(CalyxProgramJob.job_key)
        ).all()
        assert [x.status for x in jobs] == ["queued", "waiting"]
        assert db.get(CalyxProgram, response.json()["program_id"]).owner == "r1-owner"
        source = json.loads(jobs[0].input_json)["brain_request_provenance"][
            "admission_request"
        ]
        assert source["source_uris"] == ["brain://r1/source"]
        assert (
            run_deterministic_program_cycle(
                db,
                owner="other-owner",
                worker_id="wrong-owner",
                max_jobs=1,
                lease_seconds=60,
                timeout_seconds=30,
            ).attempted_jobs
            == 0
        )
        for _ in range(2):
            result = run_deterministic_program_cycle(
                db,
                owner="r1-owner",
                worker_id="r1-worker",
                max_jobs=1,
                lease_seconds=60,
                timeout_seconds=120,
                registry=AuthoritativeExecutorRegistry(
                    workspace_root=repo,
                    repository_name="jsp1440/orchid-calyx-backend",
                ),
            )
            assert result.completed_jobs == 1, json.dumps(result.as_dict())
        db.expire_all()
        assert all(x.status == "completed" for x in jobs)
        assert renewals == [150, 150]
    replay = post(c, body)
    assert replay.status_code == 200 and replay.json()["status"] == "completed"
    assert replay.json()["program_id"] == response.json()["program_id"]


def test_unrenewable_execution_budget_is_rejected_before_a_lease_is_taken(engine):
    assert post(client(engine), payload()).status_code == 200
    with Session(engine) as db:
        with pytest.raises(ValueError, match="EXECUTION_LEASE_BUDGET"):
            run_deterministic_program_cycle(
                db,
                owner="r1-owner",
                worker_id="r1-worker",
                lease_seconds=60,
                timeout_seconds=3600,
            )
        job = db.scalar(select(CalyxProgramJob))
        assert job.status == "queued" and job.lease_token is None


def test_fenced_heartbeat_cannot_renew_superseded_ownership(engine):
    assert post(client(engine), payload()).status_code == 200
    with Session(engine) as db:
        worker = PersistentProgramWorker(db)
        job = worker.claim(owner="r1-owner", worker_id="old-worker", lease_seconds=60)
        old_token, job_id = job.lease_token, job.program_job_id
        job.lease_owner = "replacement-worker"
        job.lease_token = str(uuid.uuid4())
        db.commit()
        with pytest.raises(PermissionError, match="STALE_PROGRAM_JOB_LEASE"):
            worker.heartbeat(
                program_job_id=job_id,
                worker_id="old-worker",
                lease_token=old_token,
                lease_seconds=150,
            )
