"""Database-backed Brain pulse ledger: durability, receipts, exclusivity."""

from __future__ import annotations

import os
import uuid
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.calyx_orchestrator.pulse_ledger_store import DatabasePulseLedger
from app.calyx_orchestrator.schema import ensure_orchestrator_schema

SCHEMA = "brain-calyx-autonomy-ledger.v1"


def _ledger(factory, key="acceptance"):
    return DatabasePulseLedger(factory, key=key, ledger_schema=SCHEMA)


@pytest.fixture
def sqlite_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ledger.db'}")
    return sessionmaker(engine)


def test_empty_ledger_then_durable_round_trip(sqlite_factory):
    ledger = _ledger(sqlite_factory)
    assert ledger.load() == {
        "schema": SCHEMA,
        "work": {},
        "backoff": {"consecutive_failures": 0, "until": None},
    }
    state = ledger.load()
    state["work"]["w1"] = {"state": "in_flight", "program_id": "p1"}
    ledger.save(state)
    ledger.save(state)  # idempotent update path
    # A new instance (a restarted worker) sees the same records.
    assert _ledger(sqlite_factory).load()["work"] == {
        "w1": {"state": "in_flight", "program_id": "p1"}
    }
    # Keys are isolated.
    assert _ledger(sqlite_factory, key="other").load()["work"] == {}


def test_receipts_are_append_only_and_ordered(sqlite_factory):
    ledger = _ledger(sqlite_factory)
    for index in range(3):
        ledger.append_receipt({"pulse_id": f"pulse:{index}", "n": index})
    assert [r["n"] for r in _ledger(sqlite_factory).receipts()] == [0, 1, 2]
    assert _ledger(sqlite_factory, key="other").receipts() == []


def test_unrecognized_schema_fails_closed(sqlite_factory):
    ledger = _ledger(sqlite_factory)
    ledger.save({"schema": "something-else", "work": {}})
    with pytest.raises(ValueError, match="LEDGER_SCHEMA_UNRECOGNIZED"):
        ledger.load()


def test_exclusive_is_not_reentrant_within_a_process(sqlite_factory):
    first, second = _ledger(sqlite_factory), _ledger(sqlite_factory)
    with first.exclusive() as held:
        assert held
        with second.exclusive() as contended:
            assert contended is False
    with second.exclusive() as again:
        assert again


def test_key_is_validated(sqlite_factory):
    with pytest.raises(ValueError, match="PULSE_LEDGER_KEY_INVALID"):
        DatabasePulseLedger(sqlite_factory, key="", ledger_schema=SCHEMA)


@pytest.mark.requires_postgres("TEST_DATABASE_URL")
def test_postgres_advisory_lock_excludes_other_connections():
    dsn = os.environ["TEST_DATABASE_URL"]
    url = urlsplit(dsn)
    assert (url.username, url.hostname) in {
        ("oc_local", "127.0.0.1"),
        ("ocvalidate", "localhost"),
    }
    schema = "pulse_ledger_" + uuid.uuid4().hex
    admin = create_engine(dsn)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    # Two engines model two worker hosts sharing one database.
    engines = [
        create_engine(dsn, connect_args={"options": f"-csearch_path={schema}"})
        for _ in range(2)
    ]
    try:
        with Session(engines[0]) as db:
            ensure_orchestrator_schema(db)
        key = "lock-" + uuid.uuid4().hex
        host_a, host_b = (_ledger(sessionmaker(e), key=key) for e in engines)
        with host_a.exclusive() as held:
            assert held
            with host_b.exclusive() as contended:
                assert contended is False
            state = host_a.load()
            state["work"]["w"] = {"state": "in_flight"}
            host_a.save(state)
        with host_b.exclusive() as after_release:
            assert after_release
            assert host_b.load()["work"] == {"w": {"state": "in_flight"}}
    finally:
        for engine in engines:
            engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_schema_bootstrap_is_not_fooled_by_reused_engine_ids(tmp_path):
    """Regression: the bootstrap cache was keyed by ``id(engine)``.

    Freed engines' ids are reused, so a brand-new engine on a fresh database
    looked already bootstrapped and its tables were never created
    (intermittent "no such table" failures).
    """
    import gc

    from sqlalchemy import inspect

    for index in range(30):
        engine = create_engine(f"sqlite:///{tmp_path / f'fresh-{index}.db'}")
        with Session(engine) as db:
            ensure_orchestrator_schema(db)
        assert "calyx_program_autonomy_cycles" in inspect(engine).get_table_names()
        engine.dispose()
        del engine
        gc.collect()
