"""Opt-in loopback PostgreSQL race checks; never read DATABASE_URL."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session
from test_brain_admission_replay import specification

from app.calyx_orchestrator.program_models import (
    CalyxProgram,
    CalyxProgramJob,
)
from app.calyx_orchestrator.program_repository import PersistentProgramRepository
from app.calyx_orchestrator.program_worker import PersistentProgramWorker
from app.calyx_orchestrator.schema import ensure_orchestrator_schema


@pytest.fixture
def postgres():
    dsn = os.environ.get("OC_ADMISSION_TEST_DSN")
    if not dsn:
        pytest.skip("Explicit disposable PostgreSQL DSN required")
    address = urlparse(dsn)
    if address.hostname != "127.0.0.1" or address.port != 55439:
        pytest.fail("Disposable proof DSN must use 127.0.0.1:55439")
    schema = f"admission_{uuid4().hex}"
    admin = create_engine(dsn)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(dsn, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with Session(engine) as db:
            ensure_orchestrator_schema(db)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.mark.parametrize("conflict", [False, True])
def test_concurrent_admission_has_one_persisted_identity(postgres, monkeypatch, conflict):
    barrier = Barrier(2)
    original = PersistentProgramRepository._create_program

    def synchronized(self, **kwargs):
        barrier.wait(timeout=10)
        return original(self, **kwargs)

    monkeypatch.setattr(PersistentProgramRepository, "_create_program", synchronized)

    def admit(index):
        with Session(postgres) as db:
            try:
                values = specification()
                if conflict and index:
                    values["objective"] = "Conflicting work"
                return PersistentProgramRepository(db).create_program(**values).program_id
            except ValueError as error:
                assert str(error) == "PROGRAM_IDEMPOTENCY_CONFLICT"
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(admit, [0, 1]))
    assert len({identity for identity in results if identity}) == 1
    assert results.count(None) == (1 if conflict else 0)
    with Session(postgres) as db:
        assert db.scalar(select(func.count()).select_from(CalyxProgram)) == 1
        assert db.scalar(select(func.count()).select_from(CalyxProgramJob)) == 1


def test_competing_workers_cannot_claim_a_duplicate_job(postgres):
    with Session(postgres) as db:
        repository = PersistentProgramRepository(db)
        program = repository.create_program(**specification())
        repository.start(owner="fixture-owner", program_id=program.program_id)
    barrier = Barrier(2)

    def claim(index):
        with Session(postgres) as db:
            barrier.wait(timeout=10)
            job = PersistentProgramWorker(db).claim(
                owner="fixture-owner", worker_id=f"fixture-worker-{index}", lease_seconds=60,
            )
            return job.program_job_id if job else None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, [0, 1]))
    assert results.count(None) == 1
    with Session(postgres) as db:
        job = db.scalar(select(CalyxProgramJob))
        assert job.status == "running" and job.attempt_count == 1
