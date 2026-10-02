import dataclasses
import json
import socket
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.source_federation.acquisition import AcquisitionRecord, AcquisitionRequest
from app.source_federation.acquisition_ledger import AcquisitionLedger, _as_utc
from app.source_federation.acquisition_models import AcquisitionLedgerRow
from tests.acquisition_ledger_backends import (
    LEDGER_BACKENDS,
    ledger_engine_fixture,  # noqa: F401 - the ``ledger_engine`` fixture
)


def _ledger(engine=None):
    """A ledger on ``engine`` (``ledger_engine``), else a fresh SQLite one."""
    if engine is not None:
        return AcquisitionLedger(sessionmaker(bind=engine)())
    engine = create_engine("sqlite:///:memory:")
    # Only the ledger table: the shared Base also carries schema-qualified
    # tables (e.g. research_station.*) that SQLite cannot create, so a
    # full-suite run that has imported those models fails here otherwise.
    Base.metadata.create_all(engine, tables=[AcquisitionLedgerRow.__table__])
    session = sessionmaker(bind=engine)()
    return AcquisitionLedger(session)


def _request(module="lexicon"):
    return AcquisitionRequest(
        url="https://example.org/taxon?id=7&utm_source=test",
        provider="powo",
        consumer_module=module,
    )


@LEDGER_BACKENDS
def test_duplicate_modules_coalesce_to_one_external_lease(ledger_engine):
    ledger = _ledger(ledger_engine)
    first = ledger.claim(_request("lexicon"), worker_id="w1")
    second = ledger.claim(_request("matrix"), worker_id="w2")
    assert first.action == "acquired_lease"
    assert second.action == "in_flight"


@LEDGER_BACKENDS
def test_completed_acquisition_becomes_zero_fetch_cache_hit(ledger_engine):
    ledger = _ledger(ledger_engine)
    request = _request()
    lease = ledger.claim(request, worker_id="w1")
    record = AcquisitionRecord.completed(
        request=request,
        content=b"evidence",
        provenance={"source": "fixture"},
        credits_spent=1,
    )
    ledger.complete(record, lease=lease)
    hit = ledger.claim(_request("atlas"), worker_id="w2")
    assert hit.action == "cache_hit"
    assert ledger.metrics()["credits_spent"] == 1


@LEDGER_BACKENDS
def test_failure_blocks_immediate_credit_burning_retry(ledger_engine):
    ledger = _ledger(ledger_engine)
    now = datetime.now(timezone.utc)
    claim = ledger.claim(_request(), worker_id="w1", now=now)
    ledger.fail(claim, retry_after_seconds=300, now=now)
    retry = ledger.claim(
        _request("brain"), worker_id="w2", now=now + timedelta(seconds=1)
    )
    assert retry.action == "retry_blocked"


@LEDGER_BACKENDS
def test_expired_lease_can_be_recovered(ledger_engine):
    ledger = _ledger(ledger_engine)
    now = datetime.now(timezone.utc)
    ledger.claim(_request(), worker_id="dead-worker", lease_seconds=2, now=now)
    recovered = ledger.claim(
        _request("research_station"),
        worker_id="live-worker",
        now=now + timedelta(seconds=3),
        on_expired_lease="takeover",
    )
    assert recovered.action == "acquired_lease"


@LEDGER_BACKENDS
def test_expired_lease_defaults_to_operator_review_not_takeover(ledger_engine):
    # A paid call's outcome is unknown once its lease expired unsettled; by
    # default no other worker is handed the lease (it could pay again).
    ledger = _ledger(ledger_engine)
    now = datetime.now(timezone.utc)
    dead = ledger.claim(_request(), worker_id="dead-worker", lease_seconds=2, now=now)
    later = now + timedelta(seconds=3)
    for module in ("research_station", "matrix", "atlas"):
        answer = ledger.claim(_request(module), worker_id="live", now=later)
        assert answer.action == "review_required"
        assert answer.lease_token is None
    forced = ledger.claim(
        dataclasses.replace(_request("atlas"), force_refresh=True),
        worker_id="live",
        now=later,
    )
    assert forced.action == "review_required"
    row = _row(ledger)
    assert row.status == "leased" and row.lease_token == dead.lease_token
    assert ledger.metrics(now=later)["review_required"] == 1
    # The original holder may still settle it: nobody else was authorised.
    ledger.complete(
        AcquisitionRecord.completed(
            request=_request(), content=b"late", provenance={"source": "fixture"}
        ),
        lease=dead,
        payload_json="late",
    )
    assert ledger.claim(_request("matrix"), worker_id="w", now=later).action == (
        "cache_hit"
    )


@LEDGER_BACKENDS
def test_operator_release_reopens_an_expired_lease_exactly_once(ledger_engine):
    ledger = _ledger(ledger_engine)
    now = datetime.now(timezone.utc)
    ledger.claim(_request(), worker_id="dead-worker", lease_seconds=2, now=now)
    later = now + timedelta(seconds=3)
    with pytest.raises(ValueError):
        ledger.release_for_retry(_request().key, operator_id=" ", reason="x")
    # A live lease is not reviewable.
    assert not ledger.release_for_retry(
        _request().key, operator_id="op", reason="early", now=now
    )
    assert ledger.release_for_retry(
        _request().key, operator_id="op-1", reason="confirmed unbilled", now=later
    )
    first = ledger.claim(_request("matrix"), worker_id="w1", now=later)
    second = ledger.claim(_request("atlas"), worker_id="w2", now=later)
    assert (first.action, second.action) == ("acquired_lease", "in_flight")
    provenance = json.loads(_row(ledger).provenance_json)
    assert provenance["released_by"] == "op-1"
    assert provenance["released_from"] == "leased"


@LEDGER_BACKENDS
def test_unknown_expired_lease_policy_is_refused(ledger_engine):
    ledger = _ledger(ledger_engine)
    with pytest.raises(ValueError, match="on_expired_lease"):
        ledger.claim(_request(), worker_id="w", on_expired_lease="retry")
    assert ledger.session.query(AcquisitionLedgerRow).count() == 0


# --- Timezone normalisation (naive-from-store versus aware-now) -------------
#
# SQLite returns DateTime(timezone=True) columns as NAIVE values with the
# offset dropped; PostgreSQL returns aware ones. Every comparison the ledger
# makes must behave identically on both, and must fail closed: an expired
# lease never compares valid, and an active lease or retry window never
# compares expired (which would admit a second credit-burning fetch).

_MINUS_FIVE = timezone(timedelta(hours=-5))
_PLUS_FIVE = timezone(timedelta(hours=5))


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _refuse(*_args, **_kwargs):
        raise AssertionError(
            "acquisition ledger tests must not open network connections"
        )

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


def _row(ledger):
    return ledger.session.query(AcquisitionLedgerRow).one()


def _store_naive(ledger, **fields):
    """Write naive UTC wall-clock values, as a store without tz support returns them."""
    row = _row(ledger)
    for name, value in fields.items():
        setattr(row, name, value)
    ledger.session.commit()
    ledger.session.expire_all()


def _naive_utc(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def test_as_utc_treats_naive_as_utc_and_converts_offsets():
    assert _as_utc(None) is None
    naive = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    assert _as_utc(naive) == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert _as_utc(naive).tzinfo is timezone.utc
    offset = datetime(2026, 1, 1, 7, 0, tzinfo=_MINUS_FIVE)
    assert _as_utc(offset) == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert _as_utc(offset).utcoffset() == timedelta(0)


def test_sqlite_store_really_returns_naive_values():
    # Guards the premise of this block: if the store ever returns aware
    # values the tests below still pass, but this one says why.
    ledger = _ledger()
    ledger.claim(_request(), worker_id="w1")
    ledger.session.expire_all()
    assert _row(ledger).lease_expires_at.tzinfo is None


def test_naive_stored_unexpired_lease_stays_in_flight_against_aware_now():
    ledger = _ledger()
    now = datetime.now(timezone.utc)
    ledger.claim(_request(), worker_id="w1", now=now)
    _store_naive(ledger, lease_expires_at=_naive_utc(now + timedelta(seconds=60)))
    second = ledger.claim(
        _request("matrix"), worker_id="w2", now=now + timedelta(seconds=59)
    )
    assert second.action == "in_flight"
    assert _row(ledger).lease_holder == "w1"


@pytest.mark.parametrize(
    "age", [timedelta(0), timedelta(seconds=1), timedelta(hours=6)]
)
def test_naive_stored_expired_lease_never_compares_valid(age):
    ledger = _ledger()
    now = datetime.now(timezone.utc)
    ledger.claim(_request(), worker_id="dead", now=now - timedelta(hours=7))
    _store_naive(ledger, lease_expires_at=_naive_utc(now - age))
    assert (
        ledger.claim(_request("atlas"), worker_id="live", now=now).action
        == "review_required"
    )
    recovered = ledger.claim(
        _request("atlas"), worker_id="live", now=now, on_expired_lease="takeover"
    )
    assert recovered.action == "acquired_lease"
    assert _row(ledger).lease_holder == "live"


def test_naive_stored_retry_window_blocks_until_it_passes():
    ledger = _ledger()
    now = datetime.now(timezone.utc)
    claim = ledger.claim(_request(), worker_id="w1", now=now)
    ledger.fail(claim, retry_after_seconds=300, now=now)
    _store_naive(ledger, next_retry_at=_naive_utc(now + timedelta(seconds=300)))
    blocked = ledger.claim(
        _request("brain"), worker_id="w2", now=now + timedelta(seconds=299)
    )
    assert blocked.action == "retry_blocked"
    reopened = ledger.claim(
        _request("brain"), worker_id="w2", now=now + timedelta(seconds=300)
    )
    assert reopened.action == "acquired_lease"


@LEDGER_BACKENDS
def test_non_utc_caller_offset_does_not_shorten_an_active_lease(ledger_engine):
    # SQLite drops the offset WITHOUT converting. Unless the ledger writes UTC,
    # a -05:00 instant is stored five hours early and reads back as already
    # expired, handing a second worker a duplicate paid lease.
    ledger = _ledger(ledger_engine)
    now = datetime(2026, 1, 1, 10, 0, tzinfo=_MINUS_FIVE)
    first = ledger.claim(_request(), worker_id="w1", lease_seconds=120, now=now)
    second = ledger.claim(
        _request("matrix"), worker_id="w2", now=now + timedelta(seconds=60)
    )
    assert first.action == "acquired_lease"
    assert second.action == "in_flight"


@LEDGER_BACKENDS
def test_non_utc_caller_offset_does_not_extend_an_expired_lease(ledger_engine):
    ledger = _ledger(ledger_engine)
    now = datetime(2026, 1, 1, 10, 0, tzinfo=_PLUS_FIVE)
    ledger.claim(_request(), worker_id="dead", lease_seconds=2, now=now)
    recovered = ledger.claim(
        _request("atlas"),
        worker_id="live",
        now=now + timedelta(seconds=3),
        on_expired_lease="takeover",
    )
    assert recovered.action == "acquired_lease"


@LEDGER_BACKENDS
def test_non_utc_caller_offset_does_not_shorten_a_retry_window(ledger_engine):
    ledger = _ledger(ledger_engine)
    now = datetime(2026, 1, 1, 10, 0, tzinfo=_MINUS_FIVE)
    claim = ledger.claim(_request(), worker_id="w1", now=now)
    ledger.fail(claim, retry_after_seconds=300, now=now)
    retry = ledger.claim(
        _request("brain"), worker_id="w2", now=now + timedelta(seconds=1)
    )
    assert retry.action == "retry_blocked"


@LEDGER_BACKENDS
def test_naive_caller_now_is_treated_as_utc(ledger_engine):
    ledger = _ledger(ledger_engine)
    aware = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    ledger.claim(
        _request(), worker_id="w1", lease_seconds=120, now=aware.replace(tzinfo=None)
    )
    still_leased = ledger.claim(
        _request("matrix"), worker_id="w2", now=aware + timedelta(seconds=119)
    )
    assert still_leased.action == "in_flight"
    expired = ledger.claim(
        _request("matrix"),
        worker_id="w2",
        now=aware + timedelta(seconds=120),
        on_expired_lease="takeover",
    )
    assert expired.action == "acquired_lease"


@LEDGER_BACKENDS
def test_retrieved_at_is_stored_as_utc(ledger_engine):
    ledger = _ledger(ledger_engine)
    request = _request()
    lease = ledger.claim(request, worker_id="w1")
    record = AcquisitionRecord.completed(
        request=request,
        content=b"evidence",
        provenance={"source": "fixture"},
    )
    local = datetime(2026, 1, 1, 7, 0, tzinfo=_MINUS_FIVE)
    ledger.complete(dataclasses.replace(record, retrieved_at=local), lease=lease)
    ledger.session.expire_all()
    assert _as_utc(_row(ledger).retrieved_at) == datetime(
        2026, 1, 1, 12, 0, tzinfo=timezone.utc
    )
