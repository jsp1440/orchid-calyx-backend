"""A real scientific job through the existing autonomy loop: TraitBank validation.

One ``run_forever`` scheduler (the only scheduler) runs on its own timer. Each
cycle, the Brain pulse (from an Orchid-Continuum-Brain checkout) selects the
next TraitBank validation item and submits it over the real authenticated
canonical route. Calyx admits it, leases it, and runs the registered
read-only executors (checkout evidence, then the pinned ``oc-traitbank-v1``
verdict). It persists the receipt and records the cycle durably.

Inputs are real: the batch is produced by TraitBank's own adapter from the
Darwin 1862 paper-knowledge source (public domain). A second batch carries a
coordinate in a free-text note, so the live privacy guard has something real
to refuse. No database other than the disposable schema, no network, no
ingestion, no publication.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

import runtime.program_autonomy_worker as worker_module
from app.calyx_orchestrator.autonomy_cycles import autonomy_status, record_cycle
from app.calyx_orchestrator.autonomy_policy import ProgramAutonomyPolicy
from app.calyx_orchestrator.executor_registry import AuthoritativeExecutorRegistry
from app.calyx_orchestrator.program_models import CalyxAutonomyCycle, CalyxProgramJob
from app.calyx_orchestrator.routes import router as orchestrator_router
from app.calyx_orchestrator.schema import ensure_orchestrator_schema
from app.canonical_brain.api import create_brain_router
from app.database import get_db
from app.literature_extraction.models import PaperKnowledge
from app.traitbank.adapters import TraitIndex, from_paper_knowledge
from app.traitbank.cli import load_definition_file

REPO_ROOT = Path(__file__).resolve().parents[1]
BRAIN = os.environ.get("OC_BRAIN_REPO_PATH", "").strip()
REPOSITORY = "jsp1440/orchid-calyx-backend"
BRANCH = "autonomy/traitbank-cycle"
OWNER = "backend_api_key"
API_KEY = "fixture-" + uuid.uuid4().hex
ANGRAECUM = "990000002"  # canonical taxon id used by TraitBank's own tests

pytestmark = [
    pytest.mark.requires_postgres("TEST_DATABASE_URL"),
    pytest.mark.skipif(
        not BRAIN
        or not (Path(BRAIN) / "calyx_brain" / "traitbank_validation.py").is_file(),
        reason="OC_BRAIN_REPO_PATH must name a Brain checkout with "
        "calyx_brain/traitbank_validation.py",
    ),
]


def _brain():
    if BRAIN not in sys.path:
        sys.path.append(BRAIN)
    from calyx_brain import autonomy_pulse, reasoning_contracts, traitbank_validation

    return autonomy_pulse, reasoning_contracts, traitbank_validation


@pytest.fixture
def engine():
    dsn = os.environ["TEST_DATABASE_URL"]
    url = urlsplit(dsn)
    assert url.scheme == "postgresql"
    assert (url.username, url.hostname) in {
        ("oc_local", "127.0.0.1"),
        ("ocvalidate", "localhost"),
    }
    schema = "tb_cycle_" + uuid.uuid4().hex
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


def _darwin_batch() -> dict:
    paper = PaperKnowledge.model_validate_json(
        (
            REPO_ROOT / "tests/fixtures/traitbank/darwin_1862_paper_knowledge.json"
        ).read_text()
    )
    result = from_paper_knowledge(
        paper,
        TraitIndex({d.trait_id: d for d in load_definition_file()}),
        {"Angraecum sesquipedale": ANGRAECUM}.get,
    )
    assert result.batch is not None and not result.unmapped
    return result.batch.model_dump(mode="json")


@pytest.fixture
def source(tmp_path):
    repo = tmp_path / "source"
    (repo / "data" / "traitbank").mkdir(parents=True)
    for command in (
        ["init", "-q", "-b", BRANCH],
        ["config", "user.email", "test@example.invalid"],
        ["config", "user.name", "TraitBank cycle fixture"],
    ):
        subprocess.run(["git", "-C", str(repo), *command], check=True)
    (repo / "AGENTS.md").write_text("TraitBank autonomy cycle fixture.\n")
    (repo / "requirements.txt").write_text("")
    valid = _darwin_batch()
    probe = json.loads(json.dumps(valid))
    probe["batch_key"] = valid["batch_key"] + "-privacy-probe"
    probe["assertions"][0]["notes"] = "Seen near -18.91234, 47.53612 in 1862."
    files = {}
    for name, document in (
        ("darwin_1862.json", valid),
        ("darwin_1862_privacy_probe.json", probe),
    ):
        body = json.dumps(document, indent=1, sort_keys=True).encode()
        path = f"data/traitbank/{name}"
        (repo / path).write_bytes(body)
        files[name] = {"path": path, "sha256": hashlib.sha256(body).hexdigest()}
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "traitbank batches"], check=True
    )
    return repo, files, valid


@pytest.fixture
def api(engine, monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", API_KEY)
    app = FastAPI()
    app.include_router(create_brain_router(prefix="/brain/canonical"))
    app.include_router(orchestrator_router, prefix="/brain")

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

    return client, post, get


def test_scheduler_runs_brain_selected_traitbank_validation_end_to_end(
    engine, source, api, monkeypatch, tmp_path
):
    pulse, contracts, traitbank = _brain()
    repo, files, valid = source
    client, post, get = api

    def item(work_id, name, depends=()):
        candidate = contracts.CandidateKnowledge(
            candidate_id=f"candidate:traitbank:{name}",
            subject_id=f"taxon:{ANGRAECUM}",
            predicate="has_trait_evidence",
            object_id=valid["assertions"][0]["trait_id"],
            evidence_ids=(valid["assertions"][0]["provenance"]["source_id"],),
            confidence=0.5,
        )
        packet = traitbank.build_traitbank_validation_program(
            candidate, repository=REPOSITORY, branch=BRANCH, files=[files[name]]
        )
        return pulse.WorkItem(work_id, packet, tuple(depends))

    work = [
        item("tb-darwin", "darwin_1862.json"),
        item("tb-privacy-probe", "darwin_1862_privacy_probe.json", ("tb-darwin",)),
    ]
    ledger = pulse.PulseLedger(tmp_path / "ledger.json")
    env = {"CALYX_BACKEND_BASE_URL": "http://127.0.0.1:8000", "CALYX_API_KEY": API_KEY}

    def replenish():
        return pulse.run_pulse(
            work, ledger=ledger, transport=post, status_transport=get, env=env
        )

    def recorder(result):
        with Session(engine) as db:
            return record_cycle(db, result, owner=OWNER)

    # The worker's own session factory, pointed at the disposable schema.
    monkeypatch.setattr(
        worker_module, "get_session_local", lambda: sessionmaker(engine)
    )
    registry = AuthoritativeExecutorRegistry(
        workspace_root=repo, repository_name=REPOSITORY
    )
    policy = ProgramAutonomyPolicy(
        enabled=True,
        owner=OWNER,
        worker_id="traitbank-worker",
        poll_seconds=1,
        max_jobs_per_cycle=2,
        lease_seconds=60,
        timeout_seconds=30,
    )
    cycles: list[dict] = []
    stop = threading.Event()

    def on_cycle(result):
        cycles.append(result)
        if len(cycles) == 3:
            stop.set()

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
    assert len(cycles) == 3, "scheduler did not complete three timer cycles"

    first, second, third = cycles
    # Cycle 1: Brain selected the Darwin validation; Calyx ran both jobs.
    assert [s["work_id"] for s in first["replenishment"]["submissions"]] == [
        "tb-darwin"
    ]
    assert first["classification"]["productive"] is True
    assert [j["executor_key"] for j in first["cycle"]["jobs"]] == [
        "repository_evidence_reader_v1",
        "traitbank_batch_validator_v1",
    ]
    # Cycle 2: the next timer cycle reconciled completion and replenished.
    assert [
        (r["work_id"], r["state"]) for r in second["replenishment"]["reconciled"]
    ] == [("tb-darwin", "completed")]
    assert [s["work_id"] for s in second["replenishment"]["submissions"]] == [
        "tb-privacy-probe"
    ]
    assert second["classification"]["productive"] is True
    # Cycle 3: nothing left: healthy waiting, not productive.
    assert third["classification"] == {
        "productive": False,
        "category": "no_eligible_work",
        "healthy": True,
    }
    assert first["receipt"]["persisted"] and third["receipt"]["persisted"]

    with Session(engine) as db:
        verdicts = {
            json.loads(job.input_json)["files"][0]["path"]: json.loads(
                job.evidence_json
            )["output"]
            for job in db.scalars(
                select(CalyxProgramJob).where(
                    CalyxProgramJob.role_key == "traitbank_batch_validator"
                )
            )
        }
        jobs = db.scalars(select(CalyxProgramJob)).all()
        assert len(jobs) == 4 and all(
            j.outcome == "DELIVERED" and j.attempt_count == 1 and j.lease_token is None
            for j in jobs
        )
        assert [
            r.productive
            for r in db.scalars(
                select(CalyxAutonomyCycle).order_by(CalyxAutonomyCycle.sequence)
            )
        ] == [True, True, False]
        status = autonomy_status(db, owner=OWNER)

    darwin = verdicts["data/traitbank/darwin_1862.json"]
    assert darwin["all_valid"] is True and darwin["traitbank_ingestion"] is False
    assert darwin["results"][0]["batch_key"] == valid["batch_key"]
    assert (
        darwin["results"][0]["assertions"],
        darwin["results"][0]["environment_relations"],
    ) == (1, 1)
    assert darwin["results"][0]["sha256"] == files["darwin_1862.json"]["sha256"]
    assert darwin["contract"]["contract_version"] == "oc-traitbank-v1"
    probe = verdicts["data/traitbank/darwin_1862_privacy_probe.json"]
    assert probe["all_valid"] is False
    assert {v["code"] for v in probe["results"][0]["violations"]} == {
        "COORDINATES_REFUSED"
    }

    assert status["state"] == "healthy_waiting"
    assert status["last_productive"]["job_keys"][-1].startswith(
        "build:traitbank-validation:"
    )
    # The same status is what Mission Control reads over the real route.
    live = client.get(
        "/brain/orchestrator/status", headers={"X-API-Key": API_KEY}
    ).json()
    assert live["engineering_programs"]["autonomy"]["recent"]["productive"] == 2


def test_admission_refuses_traitbank_targets_outside_the_allowlist(engine, api):
    _pulse, contracts, traitbank = _brain()
    _client, post, _get = api
    candidate = contracts.CandidateKnowledge(
        candidate_id="candidate:traitbank:escape",
        subject_id="s",
        predicate="p",
        object_id="o",
        evidence_ids=("source:x",),
        confidence=0.5,
    )
    packet = traitbank.build_traitbank_validation_program(
        candidate,
        repository=REPOSITORY,
        branch=BRANCH,
        files=[{"path": "data/traitbank/ok.json", "sha256": "a" * 64}],
    )
    # Bypass the Brain-side check to prove Calyx enforces the rule itself.
    packet["jobs"][1]["inputs"] = {
        "files": [{"path": "app/secrets.json", "sha256": "a" * 64}]
    }
    from calyx_brain.canonical_handoff import submit_canonical_handoff

    env = {"CALYX_BACKEND_BASE_URL": "http://127.0.0.1:8000", "CALYX_API_KEY": API_KEY}
    result = submit_canonical_handoff(packet, transport=post, env=env)
    assert result.outcome == "submission_rejected"
    assert result.reason == "BRAIN_HANDOFF_TRAITBANK_TARGET_NOT_ALLOWED"
    with Session(engine) as db:
        assert db.scalars(select(CalyxProgramJob)).all() == []
