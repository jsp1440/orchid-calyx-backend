"""The federation pilot pays at most once per resource, and never for held material.

``scripts/oc_firecrawl_federation_pilot.py`` used to call the Firecrawl mapper
directly, so every owner run paid again. These tests drive the script's
``main`` and count provider calls on a spy that replaces
``FirecrawlFederationMapper.map_source`` at the class, so a direct call and a
ledger-routed call are counted alike.

Provider-free: no Firecrawl call is made, Python-level socket connects are
refused, and the spy returns a profile built locally by
``build_source_profile``. Corpus audit reports below are synthetic shapes
(labelled as such), not captured production data. The budget authority is an
in-memory recorder (``FakeSpendAuthority``), never the production
reservation store.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

import scripts.oc_firecrawl_federation_pilot as pilot
from app.database import Base
from app.federation.firecrawl_mapper import (
    FirecrawlFederationMapper,
    build_source_profile,
)
from app.source_federation.acquisition_models import AcquisitionLedgerRow

POWO = "https://powo.science.kew.org/"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _refuse(*_args, **_kwargs):
        raise AssertionError("federation pilot tests must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


class SpyMapper:
    """Stands in for the paid Firecrawl Map call; thread-safe call counter."""

    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def __call__(self, _mapper_self, **kwargs):
        with self._lock:
            self.calls.append(kwargs["root_url"])
        time.sleep(self.delay)
        return build_source_profile(
            source_id=kwargs["source_id"],
            root_url=kwargs["root_url"],
            urls=(kwargs["root_url"] + "taxon/synthetic-test-url",),
            request_parameters={"search": kwargs.get("search")},
        )


class FakeSpendAuthority:
    """Records the provider-parity reservations the pilot makes (in memory)."""

    def __init__(self, *, refuse_credits: bool = False):
        self.refuse_credits = refuse_credits
        self.credit_reservations: list[tuple[str, int, int]] = []
        self.usd_reservations: list = []
        self.observations: list = []
        self.ended: list[bool] = []
        self._lock = threading.Lock()

    def _begin(self, request):
        return ("entry", request.issue_task_id)

    def _end(self, entry, *, succeeded, termination_reason):
        with self._lock:
            self.ended.append(succeeded)

    def _reserve_credits(self, task_id, amount, cap):
        if self.refuse_credits:
            raise RuntimeError("DAILY_CREDIT_CAP (synthetic)")
        with self._lock:
            self.credit_reservations.append((task_id, amount, cap))
        return {"reserved": amount}

    def _reserve(self, task_id, amount, cap):
        with self._lock:
            self.usd_reservations.append((task_id, amount, cap))

    def _observe(self, reservation, used):
        with self._lock:
            self.observations.append(used)

    def authority(self):
        from types import SimpleNamespace

        from app.federation.federation_pilot import SpendAuthority

        return SpendAuthority(
            governor=SimpleNamespace(begin=self._begin, end=self._end),
            reserve=self._reserve,
            reserve_credits=self._reserve_credits,
            observe_credits=self._observe,
        )


#: The live environment the provider gate admits (placeholders, no secret).
LIVE_ENV = {
    "NO_API_MODE": "false",
    "FIRECRAWL_KILL_SWITCH": "false",
    "FIRECRAWL_ENABLED": "true",
    "FIRECRAWL_DRY_RUN": "false",
    "PROVIDER_AUTHORIZED": "true",
    "FIRECRAWL_MAX_CALL_COST_USD": "0.01",
    "FIRECRAWL_DAILY_BUDGET_USD": "1",
    "FIRECRAWL_API_KEY": "test-placeholder-not-a-credential",
}


def _synthetic_audit(identities=()):
    """Synthetic ``audit_existing_corpus`` report shape (complete audit)."""

    def audit(_connect, *, genus):
        return {
            "schema": "oc.existing-corpus-audit.v1",
            "available": True,
            "audit_complete": True,
            "genus": genus,
            "relations": {
                "oc_import.document_revisions": {"state": "available", "count": 1},
                "oc_sources.document_inventory": {"state": "available", "count": 1},
            },
            "identities": list(identities),
            "blockers": [],
        }

    return audit


@pytest.fixture
def env(monkeypatch, tmp_path):
    """A live-authorised environment on a file SQLite database with the ledger."""
    db = tmp_path / "ledger.sqlite3"
    engine = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine, tables=[AcquisitionLedgerRow.__table__])
    engine.dispose()
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    for name, value in LIVE_ENV.items():
        monkeypatch.setenv(name, value)
    spend = FakeSpendAuthority()
    monkeypatch.setattr(
        pilot, "build_spend_authority", lambda _url, _env: spend.authority()
    )
    spy = SpyMapper()
    # A plain function, so it binds as a method like the real one.
    monkeypatch.setattr(
        FirecrawlFederationMapper,
        "map_source",
        lambda self, **kwargs: spy(self, **kwargs),
    )
    holdings = {"audit": _synthetic_audit()}

    def _holdings(_database_url):
        return pilot.CorpusHoldings(connect=None, audit=holdings["audit"])

    monkeypatch.setattr(pilot, "build_holdings_check", _holdings, raising=False)
    return {
        "db": db,
        "spy": spy,
        "holdings": holdings,
        "tmp": tmp_path,
        "spend": spend,
    }


def _run(monkeypatch, tmp: Path, *args: str, tag: str = "out"):
    output = tmp / f"{tag}.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["oc_firecrawl_federation_pilot.py", *args, "--output", str(output)],
    )
    code = pilot.main()
    return code, json.loads(output.read_text(encoding="utf-8"))


def _rows(db: Path):
    engine = create_engine(f"sqlite:///{db}")
    try:
        if not inspect(engine).has_table("acquisition_ledger"):
            return None
        with engine.connect() as conn:
            return conn.execute(
                text(
                    "SELECT status, credits_spent, consumers_json FROM acquisition_ledger"
                )
            ).all()
    finally:
        engine.dispose()


def test_repeat_runs_on_the_same_resource_make_one_paid_call(monkeypatch, env):
    first_code, first = _run(monkeypatch, env["tmp"], "--source", "powo", tag="a")
    second_code, second = _run(monkeypatch, env["tmp"], "--source", "powo", tag="b")
    third_code, _ = _run(monkeypatch, env["tmp"], "--source", "powo", tag="c")

    assert env["spy"].calls == [POWO]
    assert (first_code, second_code, third_code) == (0, 0, 0)
    assert [s["status"] for s in first["sources"]] == ["fetched"]
    assert [s["status"] for s in second["sources"]] == ["cache_hit"]
    assert first["provider_calls"] == 1 and second["provider_calls"] == 0
    assert second["profiles"][0]["urls"] == first["profiles"][0]["urls"]
    rows = _rows(env["db"])
    assert [(r.status, r.credits_spent) for r in rows] == [("complete", 1)]


def test_existing_corpus_document_makes_zero_paid_calls(monkeypatch, env):
    # Synthetic identity: a corpus revision whose source URL is the pilot root
    # (spelled differently; the existing matcher normalises it).
    env["holdings"]["audit"] = _synthetic_audit(
        [
            {
                "source_url": "https://POWO.science.kew.org?utm_source=x",
                "content_hash": "0" * 64,
                "revision_id": "rev-synthetic-1",
                "registry_id": "inv-synthetic-1",
            }
        ]
    )
    code, result = _run(monkeypatch, env["tmp"], "--source", "powo")

    assert env["spy"].calls == []
    assert code == 0
    (entry,) = result["sources"]
    assert entry["status"] == "already_held"
    assert entry["held_matches"][0]["revision_id"] == "rev-synthetic-1"
    assert "oc_import.document_revisions" in entry["stores_checked"]
    assert _rows(env["db"]) == []  # no lease was even claimed


def test_unverifiable_holdings_make_zero_paid_calls(monkeypatch, env):
    def incomplete(_connect, *, genus):
        return {
            "available": True,
            "audit_complete": False,
            "relations": {},
            "identities": [],
            "blockers": ["CORE_RELATION_ABSENT:oc_import.document_revisions"],
        }

    env["holdings"]["audit"] = incomplete
    code, result = _run(monkeypatch, env["tmp"], "--source", "powo")

    assert env["spy"].calls == []
    assert code == 3
    (entry,) = result["sources"]
    assert entry["status"] == "blocked"
    assert entry["reason"] == "EXISTING_HOLDINGS_UNVERIFIED"
    assert _rows(env["db"]) == []


def test_missing_ledger_schema_makes_zero_paid_calls(monkeypatch, env):
    engine = create_engine(f"sqlite:///{env['db']}")
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE acquisition_ledger"))
    engine.dispose()

    code, result = _run(monkeypatch, env["tmp"], "--source", "all")

    assert env["spy"].calls == []
    assert code == 2
    assert result["status"] == "aborted"
    assert result["reason"] == "ledger_schema_unavailable"
    assert "missing_table" in result["ledger_problems"]
    assert result["provider_calls"] == 0
    assert _rows(env["db"]) is None  # never created at request time


def test_incompatible_ledger_schema_makes_zero_paid_calls(monkeypatch, env):
    engine = create_engine(f"sqlite:///{env['db']}")
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE acquisition_ledger"))
        conn.execute(
            text(
                "CREATE TABLE acquisition_ledger (id INTEGER PRIMARY KEY, resource_key TEXT)"
            )
        )
    engine.dispose()

    code, result = _run(monkeypatch, env["tmp"], "--source", "powo")

    assert env["spy"].calls == []
    assert code == 2 and result["status"] == "aborted"


def test_no_database_makes_zero_paid_calls(monkeypatch, env):
    monkeypatch.delenv("DATABASE_URL")
    code, result = _run(monkeypatch, env["tmp"], "--source", "powo")

    assert env["spy"].calls == []
    assert code == 2 and result["reason"] == "LEDGER_DATABASE_REQUIRED"


def test_concurrent_pilot_runs_make_one_paid_call(monkeypatch, env):
    env["spy"].delay = 0.05  # hold the lease while the other runs claim
    count = 6
    barrier = threading.Barrier(count)
    codes: list = [None] * count
    errors: list = []
    # Every run shares one argv (process-global), so results are read from the
    # ledger and the spy rather than from per-run output files.
    monkeypatch.setattr(
        sys, "argv", ["oc_firecrawl_federation_pilot.py", "--source", "powo"]
    )

    def worker(index):
        try:
            barrier.wait(timeout=10)
            codes[index] = pilot.main()
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not errors, errors

    assert env["spy"].calls == [POWO]
    # 0 = fetched or cache hit; 3 = found the lease in flight (no paid call).
    assert set(codes) <= {0, 3}, codes
    assert [(r.status, r.credits_spent) for r in _rows(env["db"])] == [("complete", 1)]


@pytest.mark.parametrize("value", [None, "true", "TRUE", "1", "disabled"])
def test_no_api_mode_makes_zero_paid_calls(monkeypatch, env, value):
    if value is None:
        monkeypatch.delenv("NO_API_MODE")  # absent means on
    else:
        monkeypatch.setenv("NO_API_MODE", value)
    code, result = _run(monkeypatch, env["tmp"], "--source", "all")

    assert env["spy"].calls == []
    assert code == 3
    # The provider's own gate code (live_gate), not a pilot-specific one.
    assert {s["reason"] for s in result["sources"]} == {"PROVIDER_NOT_AUTHORIZED"}
    assert _rows(env["db"]) == []  # no lease taken
    assert env["spend"].credit_reservations == []


@pytest.mark.parametrize("value", ["true", "1", "on", "yes"])
def test_kill_switch_makes_zero_paid_calls(monkeypatch, env, value):
    monkeypatch.setenv("FIRECRAWL_KILL_SWITCH", value)
    code, result = _run(monkeypatch, env["tmp"], "--source", "all")

    assert env["spy"].calls == []
    assert code == 3
    assert {s["reason"] for s in result["sources"]} == {"FIRECRAWL_DISABLED"}
    assert _rows(env["db"]) == []


def test_blocked_gate_still_serves_a_held_ledger_result(monkeypatch, env):
    _run(monkeypatch, env["tmp"], "--source", "powo", tag="live")
    monkeypatch.setenv("FIRECRAWL_KILL_SWITCH", "true")
    monkeypatch.setenv("NO_API_MODE", "true")
    code, result = _run(monkeypatch, env["tmp"], "--source", "powo", tag="blocked")

    assert env["spy"].calls == [POWO]
    assert code == 0
    assert [s["status"] for s in result["sources"]] == ["cache_hit"]


def test_missing_key_takes_no_lease(monkeypatch, env):
    monkeypatch.delenv("FIRECRAWL_API_KEY")
    code, result = _run(monkeypatch, env["tmp"], "--source", "powo")

    assert env["spy"].calls == []
    assert code == 3
    assert result["sources"][0]["reason"] == "FIRECRAWL_KEY_UNAVAILABLE"
    assert _rows(env["db"]) == []


def test_in_flight_lease_elsewhere_makes_zero_paid_calls(monkeypatch, env):
    from app.federation.shared_firecrawl import SharedFirecrawlFederationService
    from app.source_federation.acquisition_ledger import AcquisitionLedger

    engine = create_engine(f"sqlite:///{env['db']}")
    session = sessionmaker(bind=engine)()
    # The same canonical resource the pilot maps (limit/sitemap are not
    # part of its identity).
    request = SharedFirecrawlFederationService.acquisition_request(
        consumer_module="other-module", root_url=POWO, search="Phragmipedium"
    )
    claim = AcquisitionLedger(session).claim(request, worker_id="another-worker")
    assert claim.action == "acquired_lease"
    session.close()
    engine.dispose()

    code, result = _run(monkeypatch, env["tmp"], "--source", "powo")

    assert env["spy"].calls == []
    assert code == 3
    assert result["sources"][0]["status"] == "in_flight"


def test_real_corpus_audit_failure_blocks_without_paid_call(monkeypatch, env):
    """The production holdings lookup, not a fake: an unreachable corpus blocks."""
    monkeypatch.setattr(
        pilot,
        "build_holdings_check",
        lambda _url: pilot.CorpusHoldings(
            connect=lambda: (_ for _ in ()).throw(OSError())
        ),
    )
    code, result = _run(monkeypatch, env["tmp"], "--source", "powo")

    assert env["spy"].calls == []
    assert code == 3
    assert result["sources"][0]["reason"] == "EXISTING_HOLDINGS_UNVERIFIED"


@pytest.mark.requires_postgres
def test_postgres_concurrent_pilot_runs_make_one_paid_call():
    from app.federation.federation_pilot import CorpusHoldings, run_pilot
    from tests.acquisition_ledger_backends import migrated_postgres_engine

    spy = SpyMapper(delay=0.05)
    mapper = type("M", (), {"map_source": lambda self, **kw: spy(self, **kw)})()
    live_env = dict(LIVE_ENV)
    spend = FakeSpendAuthority()
    with migrated_postgres_engine(pool_size=8) as engine:
        make_session = sessionmaker(bind=engine)
        count = 6
        barrier = threading.Barrier(count)
        reports: list = [None] * count

        def worker(index):
            session = make_session()
            try:
                barrier.wait(timeout=10)
                reports[index] = run_pilot(
                    session=session,
                    sources={"powo": pilot.SOURCES["powo"]},
                    mapper=mapper,
                    holdings=CorpusHoldings(None, audit=_synthetic_audit()),
                    env=live_env,
                    authority=spend.authority(),
                )
            finally:
                session.close()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

    assert spy.calls == [POWO]
    statuses = [report.sources[0]["status"] for report in reports]
    assert statuses.count("fetched") == 1, statuses
    assert sum(report.provider_calls for report in reports) == 1
    assert len(spend.credit_reservations) == 1


def test_out_of_range_limit_is_refused_before_any_lease(monkeypatch, env):
    with pytest.raises(SystemExit):
        _run(monkeypatch, env["tmp"], "--source", "powo", "--limit", "0")

    assert env["spy"].calls == []
    assert _rows(env["db"]) == []
