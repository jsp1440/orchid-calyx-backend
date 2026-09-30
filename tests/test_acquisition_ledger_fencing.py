"""Lease fencing for the paid-acquisition ledger.

A lease authorises one worker to make one paid external call. These tests pin
that a worker whose lease was superseded can neither complete nor fail the
row -- either would clear the live holder's lease and let a third worker claim
and repeat the paid call -- and that the claim path's retries are bounded.

Every test here is provider-free: no Firecrawl or other network call is made,
and Python-level socket connects are refused. The PostgreSQL race at the end
runs only when a disposable test database is configured (``requires_postgres``,
see ``tests/conftest.py``); libpq connects to it from C, below the socket
guard.
"""

from __future__ import annotations

import contextlib
import json
import logging
import random
import socket
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.federation.firecrawl_mapper import build_source_profile
from app.federation.shared_firecrawl import SharedFirecrawlFederationService
from app.source_federation.acquisition import AcquisitionRecord, AcquisitionRequest
from app.source_federation.acquisition_ledger import (
    MAX_LEDGER_ATTEMPTS,
    AcquisitionLedger,
    ClaimResult,
    LedgerContentionError,
    PaidResultUnrecordedError,
    StaleLeaseError,
)
from app.source_federation.acquisition_models import AcquisitionLedgerRow
from tests.acquisition_ledger_backends import (
    LEDGER_BACKENDS,
    ledger_engine_fixture,  # noqa: F401 - the ``ledger_engine`` fixture
    migrated_postgres_engine,
)

# Every SharedFirecrawlFederationService defaults to this worker id, so a
# fence on the holder name alone would not distinguish a stale worker from
# the live one. Most tests below use it on purpose.
SHARED_WORKER = "firecrawl-federation"
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _refuse(*_args, **_kwargs):
        raise AssertionError("ledger fencing tests must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


def _ledger(engine=None):
    """A ledger on ``engine`` (``ledger_engine``), else a fresh SQLite one."""
    if engine is not None:
        return AcquisitionLedger(sessionmaker(bind=engine)())
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[AcquisitionLedgerRow.__table__])
    return AcquisitionLedger(sessionmaker(bind=engine)())


def _request(module="lexicon", *, force_refresh=False):
    return AcquisitionRequest(
        url="https://example.org/taxon?id=7",
        provider="powo",
        consumer_module=module,
        force_refresh=force_refresh,
    )


def _record(request, content, credits=1):
    return AcquisitionRecord.completed(
        request=request,
        content=content,
        provenance={"source": "synthetic-fixture"},
        credits_spent=credits,
    )


def _row(ledger):
    ledger.session.expire_all()
    return ledger.session.query(AcquisitionLedgerRow).one()


def _snapshot(row):
    return {
        column.name: getattr(row, column.name)
        for column in AcquisitionLedgerRow.__table__.columns
    }


def _a_expired_then_b_claims(ledger, *, a_worker, b_worker):
    a = ledger.claim(_request(), worker_id=a_worker, lease_seconds=60, now=T0)
    b = ledger.claim(
        _request("matrix"),
        worker_id=b_worker,
        lease_seconds=60,
        now=T0 + timedelta(seconds=61),
        # Fencing is about what a stale holder can do AFTER another worker
        # took its lease over, so these tests opt into takeover explicitly
        # (the default for an expired lease is operator review).
        on_expired_lease="takeover",
    )
    assert a.action == b.action == "acquired_lease"
    assert a.lease_token != b.lease_token
    return a, b


WORKER_PAIRS = pytest.mark.parametrize(
    ("a_worker", "b_worker"),
    [(SHARED_WORKER, SHARED_WORKER), ("worker-a", "worker-b")],
    ids=["same-worker-id", "distinct-worker-ids"],
)


# --- Stale holder cannot touch a superseded lease ---------------------------


@WORKER_PAIRS
@LEDGER_BACKENDS
def test_stale_complete_is_refused_and_leaves_live_lease_intact(
    a_worker, b_worker, ledger_engine
):
    ledger = _ledger(ledger_engine)
    a, b = _a_expired_then_b_claims(ledger, a_worker=a_worker, b_worker=b_worker)
    before = _snapshot(_row(ledger))

    with pytest.raises(StaleLeaseError) as excinfo:
        ledger.complete(_record(_request(), b"stale-A"), lease=a, payload_json="A")

    assert excinfo.value.unrecorded_credits == 1
    assert _snapshot(_row(ledger)) == before
    row = _row(ledger)
    assert row.status == "leased"
    assert row.lease_token == b.lease_token
    assert row.payload_json is None
    assert row.credits_spent == 0
    # B's live lease still coalesces: a third worker does not get to pay again.
    third = ledger.claim(
        _request("atlas"), worker_id=SHARED_WORKER, now=T0 + timedelta(seconds=62)
    )
    assert third.action == "in_flight"


@WORKER_PAIRS
@LEDGER_BACKENDS
def test_stale_fail_is_refused_and_leaves_live_lease_intact(
    a_worker, b_worker, ledger_engine
):
    ledger = _ledger(ledger_engine)
    a, _b = _a_expired_then_b_claims(ledger, a_worker=a_worker, b_worker=b_worker)
    before = _snapshot(_row(ledger))

    with pytest.raises(StaleLeaseError):
        ledger.fail(a, retry_after_seconds=300, now=T0 + timedelta(seconds=62))

    assert _snapshot(_row(ledger)) == before
    row = _row(ledger)
    assert row.failure_count == 0
    assert row.next_retry_at is None
    third = ledger.claim(
        _request("atlas"), worker_id=SHARED_WORKER, now=T0 + timedelta(seconds=63)
    )
    assert third.action == "in_flight"


@WORKER_PAIRS
@LEDGER_BACKENDS
def test_live_holder_completes_after_stale_attempt(a_worker, b_worker, ledger_engine):
    ledger = _ledger(ledger_engine)
    a, b = _a_expired_then_b_claims(ledger, a_worker=a_worker, b_worker=b_worker)
    with pytest.raises(StaleLeaseError):
        ledger.complete(_record(_request(), b"stale-A"), lease=a, payload_json="A")

    ledger.complete(_record(_request(), b"live-B"), lease=b, payload_json="B")

    row = _row(ledger)
    assert row.status == "complete"
    assert row.payload_json == "B"
    assert row.credits_spent == 1
    # Released: no holder, and the token rotated to one nobody holds.
    assert row.lease_holder is None
    assert row.lease_token not in {None, a.lease_token, b.lease_token}
    assert ledger.cached_payload(b.resource_key) == "B"
    # And the stale holder cannot overwrite the completed result afterwards.
    with pytest.raises(StaleLeaseError):
        ledger.complete(_record(_request(), b"stale-A"), lease=a, payload_json="A")
    assert _row(ledger).payload_json == "B"


@LEDGER_BACKENDS
def test_live_holder_fail_still_opens_retry_window(ledger_engine):
    ledger = _ledger(ledger_engine)
    lease = ledger.claim(_request(), worker_id=SHARED_WORKER, now=T0)
    ledger.fail(lease, retry_after_seconds=300, now=T0)
    row = _row(ledger)
    assert row.status == "failed"
    assert row.failure_count == 1
    assert row.lease_holder is None
    assert row.lease_token not in {None, lease.lease_token}
    blocked = ledger.claim(
        _request("brain"), worker_id=SHARED_WORKER, now=T0 + timedelta(seconds=1)
    )
    assert blocked.action == "retry_blocked"


@LEDGER_BACKENDS
def test_expired_but_unreclaimed_lease_may_still_complete(ledger_engine):
    # Nobody else was authorised in the meantime, so the result is kept.
    ledger = _ledger(ledger_engine)
    lease = ledger.claim(_request(), worker_id="slow", lease_seconds=1, now=T0)
    ledger.complete(_record(_request(), b"late"), lease=lease, payload_json="late")
    assert _row(ledger).status == "complete"


@LEDGER_BACKENDS
def test_lease_cannot_be_used_twice(ledger_engine):
    ledger = _ledger(ledger_engine)
    lease = ledger.claim(_request(), worker_id=SHARED_WORKER, now=T0)
    ledger.complete(_record(_request(), b"once"), lease=lease, payload_json="once")
    with pytest.raises(StaleLeaseError):
        ledger.complete(_record(_request(), b"twice"), lease=lease, payload_json="x")
    with pytest.raises(StaleLeaseError):
        ledger.fail(lease, now=T0)
    row = _row(ledger)
    assert (row.status, row.payload_json, row.credits_spent) == ("complete", "once", 1)
    assert row.failure_count == 0


@LEDGER_BACKENDS
def test_force_refresh_lease_supersedes_nothing_it_should_not(ledger_engine):
    ledger = _ledger(ledger_engine)
    first = ledger.claim(_request(), worker_id=SHARED_WORKER, now=T0)
    ledger.complete(_record(_request(), b"v1"), lease=first, payload_json="v1")
    refresh = ledger.claim(
        _request("atlas", force_refresh=True), worker_id=SHARED_WORKER, now=T0
    )
    assert refresh.action == "acquired_lease"
    with pytest.raises(StaleLeaseError):
        ledger.complete(_record(_request(), b"old"), lease=first, payload_json="old")
    ledger.complete(_record(_request(), b"v2"), lease=refresh, payload_json="v2")
    assert _row(ledger).payload_json == "v2"


@LEDGER_BACKENDS
def test_non_lease_results_and_raw_keys_are_refused(ledger_engine):
    ledger = _ledger(ledger_engine)
    lease = ledger.claim(_request(), worker_id="w1", now=T0)
    in_flight = ledger.claim(_request("matrix"), worker_id="w2", now=T0)
    assert in_flight.action == "in_flight"
    before = _snapshot(_row(ledger))
    with pytest.raises(StaleLeaseError):
        ledger.complete(_record(_request(), b"x"), lease=in_flight)
    with pytest.raises(StaleLeaseError):
        ledger.fail(in_flight, now=T0)
    with pytest.raises(TypeError):
        ledger.fail(lease.resource_key, now=T0)  # the pre-fencing call shape
    forged = ClaimResult(
        "acquired_lease", lease.row_id, lease.resource_key, "w1", "0" * 32
    )
    with pytest.raises(StaleLeaseError):
        ledger.complete(_record(_request(), b"x"), lease=forged)
    other = AcquisitionRequest(
        url="https://example.org/other", provider="powo", consumer_module="x"
    )
    with pytest.raises(ValueError):
        ledger.complete(_record(other, b"x"), lease=lease)
    assert _snapshot(_row(ledger)) == before


# --- Claim compare-and-swap ---------------------------------------------------


def test_claim_takeover_rereads_a_row_that_cycled_since_it_was_read(
    tmp_path, monkeypatch
):
    """ABA: C reads a failed row; D claims and completes it before C's write.

    C must see the completed row (cache hit), not take over a finished
    acquisition and pay for it again. A token cleared on release would look
    the same before and after D's cycle; a rotated one does not.
    """
    import app.source_federation.acquisition_ledger as ledger_module

    engine = create_engine(
        f"sqlite:///{tmp_path / 'aba.sqlite3'}", connect_args={"timeout": 30}
    )
    Base.metadata.create_all(engine, tables=[AcquisitionLedgerRow.__table__])
    make = sessionmaker(bind=engine)
    seed = AcquisitionLedger(make())
    first = seed.claim(_request(), worker_id=SHARED_WORKER, now=T0)
    seed.fail(first, retry_after_seconds=1, now=T0)

    real_new_token = ledger_module._new_lease_token
    interleaved = {"done": False}

    def _interleave():
        if not interleaved["done"]:
            interleaved["done"] = True
            other = AcquisitionLedger(make())
            d = other.claim(
                _request("d"), worker_id=SHARED_WORKER, now=T0 + timedelta(seconds=5)
            )
            assert d.action == "acquired_lease"
            other.complete(_record(_request(), b"D"), lease=d, payload_json="D")
        return real_new_token()

    monkeypatch.setattr(ledger_module, "_new_lease_token", _interleave)
    c = AcquisitionLedger(make()).claim(
        _request("c"), worker_id=SHARED_WORKER, now=T0 + timedelta(seconds=5)
    )
    assert interleaved["done"]
    assert c.action == "cache_hit"
    check = make().query(AcquisitionLedgerRow).one()
    assert (check.status, check.payload_json, check.credits_spent) == (
        "complete",
        "D",
        1,
    )
    engine.dispose()


# --- Bounded retry -----------------------------------------------------------


@LEDGER_BACKENDS
def test_insert_race_retry_is_bounded(monkeypatch, ledger_engine):
    ledger = _ledger(ledger_engine)
    commits = []

    def _always_lose(*_args, **_kwargs):
        commits.append(1)
        raise IntegrityError("INSERT", {}, Exception("unique violation (simulated)"))

    monkeypatch.setattr(ledger.session, "commit", _always_lose)
    with pytest.raises(LedgerContentionError) as excinfo:
        ledger.claim(_request(), worker_id=SHARED_WORKER, now=T0)
    assert len(commits) == MAX_LEDGER_ATTEMPTS == 3
    assert excinfo.value.attempts == 3


@LEDGER_BACKENDS
def test_insert_race_recovers_when_the_winner_is_visible(monkeypatch, ledger_engine):
    # One lost insert, then the re-read sees the winner's live lease.
    ledger = _ledger(ledger_engine)
    winner = AcquisitionLedger(ledger.session)
    real_commit = ledger.session.commit
    state = {"lost": False}

    def _lose_once():
        if not state["lost"]:
            state["lost"] = True
            ledger.session.rollback()
            monkeypatch.setattr(ledger.session, "commit", real_commit)
            winner.claim(_request("matrix"), worker_id="winner", now=T0)
            raise IntegrityError("INSERT", {}, Exception("unique violation"))
        return real_commit()

    monkeypatch.setattr(ledger.session, "commit", _lose_once)
    result = ledger.claim(_request(), worker_id="loser", now=T0)
    assert result.action == "in_flight"
    assert _row(ledger).lease_holder == "winner"


# --- Service level: a superseded call does not clobber the live lease --------


def _service(session, mapper):
    return SharedFirecrawlFederationService(session, mapper=mapper)


def _map_kwargs(module):
    return {
        "consumer_module": module,
        "source_id": "powo",
        "root_url": "https://powo.science.kew.org/",
        "search": "Phragmipedium",
        "limit": 25,
    }


def _profile():
    return build_source_profile(
        source_id="powo",
        root_url="https://powo.science.kew.org/",
        urls=("https://powo.science.kew.org/taxon/test",),
    )


def _supersede_during_call(session):
    """Mapper side effect: while A's paid call runs, its lease is taken over."""
    ledger = AcquisitionLedger(session)

    def _takeover():
        row = session.query(AcquisitionLedgerRow).one()
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
        lease_b = ledger.claim(
            SharedFirecrawlFederationService.acquisition_request(
                consumer_module="matrix",
                root_url="https://powo.science.kew.org/",
                search="Phragmipedium",
            ),
            worker_id=SHARED_WORKER,
            on_expired_lease="takeover",
        )
        assert lease_b.action == "acquired_lease"
        return lease_b

    return _takeover


def _session(engine=None):
    if engine is not None:
        return sessionmaker(bind=engine)()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[AcquisitionLedgerRow.__table__])
    return sessionmaker(bind=engine)()


@LEDGER_BACKENDS
def test_service_superseded_success_returns_stale_and_keeps_live_lease(
    caplog, ledger_engine
):
    caplog.set_level(logging.WARNING, logger="app.federation.shared_firecrawl")
    session = _session(ledger_engine)
    takeover = _supersede_during_call(session)
    held = {}
    mapper = Mock()

    def _slow_success(**_kwargs):
        held["b"] = takeover()
        return _profile()

    mapper.map_source.side_effect = _slow_success
    status, profile = _service(session, mapper).map_source(**_map_kwargs("lexicon"))

    assert (status, profile) == ("stale_lease", None)
    # The stale holder's paid credit is reported, not dropped silently.
    stale_logs = [r.getMessage() for r in caplog.records if "superseded" in r.msg]
    assert len(stale_logs) == 1
    assert "unrecorded_credits=1" in stale_logs[0]
    assert "consumer=lexicon" in stale_logs[0]
    session.expire_all()
    row = session.query(AcquisitionLedgerRow).one()
    assert row.status == "leased"
    assert row.lease_token == held["b"].lease_token
    assert row.payload_json is None
    # A third consumer is coalesced onto B's lease: no second paid call.
    third = Mock()
    status, _ = _service(session, third).map_source(**_map_kwargs("atlas"))
    assert status == "in_flight"
    third.map_source.assert_not_called()


@LEDGER_BACKENDS
def test_service_superseded_failure_reraises_and_keeps_live_lease(ledger_engine):
    session = _session(ledger_engine)
    takeover = _supersede_during_call(session)
    held = {}
    mapper = Mock()

    def _slow_failure(**_kwargs):
        held["b"] = takeover()
        raise RuntimeError("provider error (simulated)")

    mapper.map_source.side_effect = _slow_failure
    with pytest.raises(RuntimeError, match="provider error"):
        _service(session, mapper).map_source(**_map_kwargs("lexicon"))

    session.expire_all()
    row = session.query(AcquisitionLedgerRow).one()
    assert row.status == "leased"
    assert row.lease_token == held["b"].lease_token
    assert row.failure_count == 0 and row.next_retry_at is None


# --- A matched fence always records the paid result -------------------------
#
# Consumer bookkeeping is not lease state. A consumer joining an in-flight
# lease rewrites ``consumers_json``; that must never veto, retry away, or
# discard the live holder's paid result (repair of checker finding on #1697).


def _file_engine(tmp_path, name="ledger.sqlite3"):
    engine = create_engine(
        f"sqlite:///{tmp_path / name}",
        connect_args={"timeout": 30, "check_same_thread": False},
    )
    Base.metadata.create_all(engine, tables=[AcquisitionLedgerRow.__table__])
    return engine


def _inject_before_updates(session, action, *, times):
    """Run ``action`` before each of the next ``times`` ORM UPDATEs on ``session``.

    Fires after ``complete`` has read the row and before its UPDATE executes,
    which is exactly the window a concurrent consumer claim lands in.
    """
    remaining = {"n": times, "fired": 0}

    @event.listens_for(session, "do_orm_execute")
    def _hook(orm_execute_state):
        if orm_execute_state.is_update and remaining["n"] > 0:
            remaining["n"] -= 1
            remaining["fired"] += 1
            action(remaining["fired"])

    return remaining


def test_consumer_claim_between_read_and_update_cannot_discard_result(tmp_path):
    engine = _file_engine(tmp_path)
    make = sessionmaker(bind=engine)
    holder = AcquisitionLedger(make())
    lease = holder.claim(_request("lexicon"), worker_id=SHARED_WORKER, now=T0)

    def _consumer_joins(n):
        other = AcquisitionLedger(make())
        joined = other.claim(_request(f"joiner{n}"), worker_id=SHARED_WORKER, now=T0)
        assert joined.action == "in_flight"
        other.session.close()

    fired = _inject_before_updates(holder.session, _consumer_joins, times=1)
    holder.complete(_record(_request(), b"paid"), lease=lease, payload_json="paid")

    assert fired["fired"] == 1
    row = make().query(AcquisitionLedgerRow).one()
    assert (row.status, row.payload_json, row.credits_spent) == ("complete", "paid", 1)
    assert row.failure_count == 0
    assert {"lexicon", "joiner1"} <= set(json.loads(row.consumers_json))
    engine.dispose()


def test_consumer_claims_before_every_update_still_record_result(tmp_path, caplog):
    # Worst case: the list changes before EVERY write, including each
    # best-effort merge attempt. The result still lands; only the merge
    # gives up, with a warning, and complete() does not raise.
    caplog.set_level(logging.WARNING, logger="app.source_federation.acquisition_ledger")
    engine = _file_engine(tmp_path)
    make = sessionmaker(bind=engine)
    holder = AcquisitionLedger(make())
    lease = holder.claim(_request("lexicon"), worker_id=SHARED_WORKER, now=T0)

    def _rewrite_consumers(n):
        other = make()
        row = other.query(AcquisitionLedgerRow).one()
        row.consumers_json = json.dumps([f"joiner{n}"])
        other.commit()
        other.close()

    fired = _inject_before_updates(holder.session, _rewrite_consumers, times=99)
    holder.complete(_record(_request(), b"paid"), lease=lease, payload_json="paid")

    assert fired["fired"] == 1 + MAX_LEDGER_ATTEMPTS
    row = make().query(AcquisitionLedgerRow).one()
    assert (row.status, row.payload_json, row.credits_spent) == ("complete", "paid", 1)
    assert any("not merged" in r.getMessage() for r in caplog.records)
    engine.dispose()


def test_transient_lock_error_on_complete_is_retried_then_bounded(tmp_path):
    engine = _file_engine(tmp_path)
    make = sessionmaker(bind=engine)

    def _locked(_n):
        raise OperationalError("UPDATE", {}, Exception("database is locked"))

    holder = AcquisitionLedger(make())
    lease = holder.claim(_request(), worker_id=SHARED_WORKER, now=T0)
    _inject_before_updates(holder.session, _locked, times=1)
    holder.complete(_record(_request(), b"paid"), lease=lease, payload_json="paid")
    assert make().query(AcquisitionLedgerRow).one().credits_spent == 1

    holder = AcquisitionLedger(make())
    holder.session.query(AcquisitionLedgerRow).delete()
    holder.session.commit()
    lease = holder.claim(_request(), worker_id=SHARED_WORKER, now=T0)
    _inject_before_updates(holder.session, _locked, times=MAX_LEDGER_ATTEMPTS)
    with pytest.raises(LedgerContentionError) as excinfo:
        holder.complete(_record(_request(), b"paid"), lease=lease)
    assert excinfo.value.operation == "complete"
    assert "complete for" in str(excinfo.value)
    assert "acquiring a lease" not in str(excinfo.value)
    row = make().query(AcquisitionLedgerRow).one()
    assert row.status == "leased" and row.lease_token == lease.lease_token
    engine.dispose()


@LEDGER_BACKENDS
def test_service_never_fails_a_paid_success_on_ledger_error(caplog, ledger_engine):
    caplog.set_level(logging.ERROR, logger="app.federation.shared_firecrawl")
    session = _session(ledger_engine)
    mapper = Mock()
    mapper.map_source.return_value = _profile()
    service = _service(session, mapper)
    service.ledger.fail = Mock(wraps=service.ledger.fail)
    service.ledger.complete = Mock(
        side_effect=LedgerContentionError(
            resource_key="k", operation="complete", attempts=3
        )
    )
    with pytest.raises(PaidResultUnrecordedError) as excinfo:
        service.map_source(**_map_kwargs("lexicon"))
    assert isinstance(excinfo.value.__cause__, LedgerContentionError)
    assert excinfo.value.held_for_review is True

    service.ledger.fail.assert_not_called()
    session.expire_all()
    row = session.query(AcquisitionLedgerRow).one()
    # Held for operator review, not marked failed (no retry window to wait
    # out) and not left to a lease expiry another worker could take over.
    assert row.status == "review_required"
    assert row.failure_count == 0 and row.next_retry_at is None
    assert row.credits_spent == 1 and row.lease_holder is None
    errors = [r.getMessage() for r in caplog.records if "not recorded" in r.msg]
    assert len(errors) == 1 and "unrecorded_credits=1" in errors[0]
    # No worker re-pays: not a later caller, not a forced refresh.
    again = _service(_session(ledger_engine), mapper)
    assert again.map_source(**_map_kwargs("matrix"))[0] == "review_required"
    assert (
        again.map_source(
            **_map_kwargs("atlas"), force_refresh=True, operator_override="op"
        )[0]
        == "review_required"
    )
    mapper.map_source.assert_called_once()


# --- Concurrency -------------------------------------------------------------


def _run_threads(count, target):
    barrier = threading.Barrier(count)
    results = [None] * count
    errors = []

    def _worker(index):
        try:
            barrier.wait(timeout=10)
            results[index] = target(index)
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads)
    assert not errors, errors
    return results


def _race_suite(make_session, *, rounds):
    """Invariants that must hold on every backend under real concurrency."""
    # 1. Many workers (same id) take over one expired lease: exactly one wins.
    for round_no in range(rounds):
        seed = make_session()
        seed.query(AcquisitionLedgerRow).delete()
        seed.commit()
        AcquisitionLedger(seed).claim(
            _request(), worker_id=SHARED_WORKER, lease_seconds=1, now=T0
        )
        seed.close()

        def _claim(index):
            session = make_session()
            try:
                return (
                    AcquisitionLedger(session)
                    .claim(
                        _request(f"m{index}"),
                        worker_id=SHARED_WORKER,
                        now=T0 + timedelta(seconds=10),
                        on_expired_lease="takeover",
                    )
                    .action
                )
            finally:
                session.close()

        actions = _run_threads(8, _claim)
        assert actions.count("acquired_lease") == 1, (round_no, actions)
        assert set(actions) <= {"acquired_lease", "in_flight"}

    # 2. Stale A completes/fails while C races to take over A's expired lease:
    #    exactly one of them wins, and C's lease is never clobbered.
    for round_no in range(rounds):
        for op in ("complete", "fail"):
            seed = make_session()
            seed.query(AcquisitionLedgerRow).delete()
            seed.commit()
            lease_a = AcquisitionLedger(seed).claim(
                _request(), worker_id=SHARED_WORKER, lease_seconds=1, now=T0
            )
            seed.close()

            def _race(index, op=op, lease_a=lease_a):
                session = make_session()
                ledger = AcquisitionLedger(session)
                try:
                    if index == 0:
                        try:
                            if op == "complete":
                                ledger.complete(
                                    _record(_request(), b"A"),
                                    lease=lease_a,
                                    payload_json="A",
                                )
                            else:
                                ledger.fail(lease_a, now=T0 + timedelta(seconds=10))
                            return ("A", "won")
                        except StaleLeaseError:
                            return ("A", "stale")
                    return (
                        "C",
                        ledger.claim(
                            _request("c"),
                            worker_id=SHARED_WORKER,
                            now=T0 + timedelta(seconds=10),
                            on_expired_lease="takeover",
                        ),
                    )
                finally:
                    session.close()

            (_, a_outcome), (_, c_claim) = _run_threads(2, _race)
            check = make_session()
            row = check.query(AcquisitionLedgerRow).one()
            if a_outcome == "won":
                assert c_claim.action in {"cache_hit", "retry_blocked"}, (
                    round_no,
                    op,
                    c_claim,
                )
                assert row.status == ("complete" if op == "complete" else "failed")
            else:
                assert c_claim.action == "acquired_lease", (round_no, op, c_claim)
                assert row.status == "leased"
                assert row.lease_token == c_claim.lease_token
                assert row.payload_json is None and row.failure_count == 0
            check.close()


def test_sqlite_threads_never_hand_out_two_leases_or_clobber_one(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ledger.sqlite3'}",
        connect_args={"timeout": 30, "check_same_thread": False},
    )
    Base.metadata.create_all(engine, tables=[AcquisitionLedgerRow.__table__])
    try:
        _race_suite(sessionmaker(bind=engine), rounds=15)
    finally:
        engine.dispose()


class _CountingMapper:
    """Thread-safe provider stand-in: counts would-be paid calls per key."""

    def __init__(self):
        self._lock = threading.Lock()
        self.calls = Counter()

    def map_source(self, **kwargs):
        with self._lock:
            self.calls[kwargs["search"]] += 1
        time.sleep(0.002)  # widen the in-flight window for joining consumers
        return build_source_profile(
            source_id=kwargs["source_id"],
            root_url=kwargs["root_url"],
            urls=(f"https://powo.science.kew.org/taxon/{kwargs['search']}",),
        )


def _service_stress(make_session, *, keys=100, threads=12):
    """Many consumers per key through the service: zero discarded paid results."""
    mapper = _CountingMapper()
    searches = [f"S{index:03d}" for index in range(keys)]

    def _consumer(index):
        session = make_session()
        service = SharedFirecrawlFederationService(session, mapper=mapper)
        order = list(searches)
        random.Random(index).shuffle(order)
        outcomes = []
        try:
            for search in order:
                # A consumer that finds the key in flight keeps asking, and
                # each ask arrives as a distinct module, so every poll is a
                # real ``consumers_json`` write racing the holder's complete().
                for poll in range(400):
                    status, _ = service.map_source(
                        consumer_module=f"module{index}.{poll}",
                        source_id="powo",
                        root_url="https://powo.science.kew.org/",
                        search=search,
                        limit=25,
                    )
                    if status != "in_flight":
                        break
                outcomes.append(status)
        finally:
            session.close()
        return outcomes

    outcomes = Counter(
        status for result in _run_threads(threads, _consumer) for status in result
    )
    assert set(outcomes) <= {"fetched", "cache_hit"}, outcomes
    # Exactly one paid call per key, and every one of them was recorded.
    assert set(mapper.calls) == set(searches)
    assert set(mapper.calls.values()) == {1}, mapper.calls
    assert outcomes["fetched"] == keys
    check = make_session()
    rows = check.query(AcquisitionLedgerRow).all()
    discarded = [
        row.resource_key
        for row in rows
        if row.status != "complete" or row.credits_spent != 1 or not row.payload_json
    ]
    assert discarded == []
    assert len(rows) == keys
    assert sum(row.failure_count for row in rows) == 0
    check.close()
    return outcomes


def test_sqlite_service_stress_discards_no_paid_result(tmp_path):
    engine = _file_engine(tmp_path, "stress.sqlite3")
    try:
        _service_stress(sessionmaker(bind=engine))
    finally:
        engine.dispose()


@contextlib.contextmanager
def _postgres_engine():
    # Built by the production migration, not create_all, so these races run
    # against the schema production will actually have.
    with migrated_postgres_engine(pool_size=14, max_overflow=4) as engine:
        yield engine


@pytest.mark.requires_postgres
def test_postgres_threads_never_hand_out_two_leases_or_clobber_one():
    with _postgres_engine() as engine:
        _race_suite(sessionmaker(bind=engine), rounds=15)


@pytest.mark.requires_postgres
def test_postgres_service_stress_discards_no_paid_result():
    with _postgres_engine() as engine:
        _service_stress(sessionmaker(bind=engine))
