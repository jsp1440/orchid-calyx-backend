"""Firecrawl Map duplicate-spend closure: lease/deadline, coverage, gate parity, URLs.

Provider-free. Every Firecrawl Map call below goes to a local spy or to an
``httpx.MockTransport``; the real httpx transport and Python-level socket
connects are replaced with functions that fail the test (and count), so a
real network call cannot pass silently. Profiles are built locally by
``build_source_profile``; corpus audit reports are synthetic shapes.
"""

from __future__ import annotations

import json
import logging
import socket
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

import scripts.oc_firecrawl_federation_pilot as pilot_script
from app.federation import federation_pilot
from app.federation.federation_pilot import CorpusHoldings, provider_gate, run_pilot
from app.federation.firecrawl_mapper import (
    FirecrawlFederationMapper,
    build_source_profile,
)
from app.federation.shared_firecrawl import SharedFirecrawlFederationService
from app.literature_extraction import firecrawl_provider
from app.literature_extraction.firecrawl_acquisition import held_source_match
from app.literature_extraction.firecrawl_provider import (
    AcquisitionBlocked,
    FirecrawlConfig,
    FirecrawlProvider,
)
from app.source_federation.acquisition import (
    AcquisitionRecord,
    canonicalize_url,
    resource_key,
)
from app.source_federation.acquisition_ledger import (
    AcquisitionLedger,
    PaidResultUnrecordedError,
)
from app.source_federation.acquisition_models import AcquisitionLedgerRow
from app.source_federation.deadline import (
    PaidCallDeadlineExceeded,
    call_with_deadline,
    lease_seconds_for,
)
from tests.acquisition_ledger_backends import (
    LEDGER_BACKENDS,
    ledger_engine_fixture,  # noqa: F401 - the ``ledger_engine`` fixture
)
from tests.test_firecrawl_federation_pilot_ledger import (
    LIVE_ENV,
    FakeSpendAuthority,
    _synthetic_audit,
)

POWO = "https://powo.science.kew.org/"


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Zero real provider calls: the real transport and sockets fail loudly."""
    real_calls: list[str] = []

    def _real_transport(self, request):
        real_calls.append(str(request.url))
        raise AssertionError("a real httpx transport was used")

    def _refuse(*_args, **_kwargs):
        real_calls.append("socket")
        raise AssertionError("tests must not open network connections")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _real_transport)
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    yield real_calls
    assert real_calls == [], real_calls


class Spy:
    """Stands in for the paid Map call; counts every invocation."""

    def __init__(self, *, delay: float = 0.0, total_timeout_seconds=None):
        self.delay = delay
        self.calls: list[dict] = []
        self._lock = threading.Lock()
        if total_timeout_seconds is not None:
            self.total_timeout_seconds = total_timeout_seconds
        self.during_call = None

    def map_source(self, **kwargs):
        with self._lock:
            self.calls.append(kwargs)
        if self.during_call is not None:
            self.during_call()
        time.sleep(self.delay)
        return build_source_profile(
            source_id=kwargs["source_id"],
            root_url=kwargs["root_url"],
            urls=(kwargs["root_url"] + "taxon/synthetic-test-url",),
            request_parameters={
                "limit": kwargs["limit"],
                "sitemap": kwargs["sitemap"],
            },
        )


def _map(service, module="lexicon", **overrides):
    kwargs = {
        "consumer_module": module,
        "source_id": "powo",
        "root_url": POWO,
        "search": "Phragmipedium",
        "limit": 50,
        "sitemap": "include",
    }
    kwargs.update(overrides)
    return service.map_source(**kwargs)


def _row(engine):
    session = sessionmaker(bind=engine)()
    try:
        return session.query(AcquisitionLedgerRow).one()
    finally:
        session.close()


def _slow_client(seconds: float, calls: list):
    def handler(request):
        calls.append(str(request.url))
        time.sleep(seconds)
        return httpx.Response(200, json={"success": True, "links": [POWO]})

    return httpx.Client(transport=httpx.MockTransport(handler))


# --- 1. Lease versus wall-clock of the paid call ------------------------------


def test_lease_is_derived_from_the_declared_deadline_plus_margin():
    mapper = FirecrawlFederationMapper(api_key="placeholder", total_timeout_seconds=30)
    service = SharedFirecrawlFederationService(Mock(), mapper=mapper)
    assert service.call_deadline_seconds == 30.0
    assert service.lease_seconds == 90
    assert service.lease_seconds > service.call_deadline_seconds
    # A mapper that declares nothing gets the module default, never "no bound".
    default = SharedFirecrawlFederationService(Mock(), mapper=Mock(spec=["map_source"]))
    assert default.lease_seconds == lease_seconds_for(60.0) == 120
    for bad in (0, -1, float("inf"), float("nan"), 901):
        with pytest.raises(ValueError):
            FirecrawlFederationMapper(api_key="placeholder", total_timeout_seconds=bad)
    with pytest.raises(TypeError):
        FirecrawlFederationMapper(api_key="placeholder", total_timeout_seconds=True)
    with pytest.raises(ValueError):
        lease_seconds_for(30, margin_seconds=0)


def test_deadline_bounds_the_whole_exchange_not_each_phase():
    calls: list = []
    mapper = FirecrawlFederationMapper(
        api_key="test-placeholder-not-a-credential",
        client=_slow_client(1.5, calls),
        total_timeout_seconds=0.2,
    )
    started = time.monotonic()
    with pytest.raises(PaidCallDeadlineExceeded):
        mapper.map_source(source_id="powo", root_url=POWO, limit=10)
    assert time.monotonic() - started < 1.0
    assert len(calls) == 1
    # A result that arrives in time is returned unchanged.
    assert call_with_deadline(lambda: 7, 1) == 7
    with pytest.raises(KeyError):
        call_with_deadline(lambda: {}["missing"], 1)


@LEDGER_BACKENDS
def test_slow_call_is_settled_inside_its_lease_and_nobody_re_pays(ledger_engine):
    calls: list = []
    slow = FirecrawlFederationMapper(
        api_key="test-placeholder-not-a-credential",
        client=_slow_client(1.5, calls),
        total_timeout_seconds=0.2,
    )
    make = sessionmaker(bind=ledger_engine)
    service = SharedFirecrawlFederationService(
        make(), mapper=slow, lease_margin_seconds=1
    )
    assert service.lease_seconds == 2
    claimed_at = datetime.now(timezone.utc)
    with pytest.raises(PaidCallDeadlineExceeded):
        _map(service)
    settled_at = datetime.now(timezone.utc)
    assert settled_at < claimed_at + timedelta(seconds=service.lease_seconds)
    row = _row(ledger_engine)
    assert row.status == "failed" and row.failure_count == 1
    assert row.lease_expires_at is None and row.next_retry_at is not None

    fast = Spy()
    other = SharedFirecrawlFederationService(make(), mapper=fast)
    assert _map(other, module="matrix") == ("retry_blocked", None)
    assert fast.calls == [] and len(calls) == 1


@LEDGER_BACKENDS
def test_call_that_outlives_its_lease_is_not_taken_over(ledger_engine):
    """Before: lease 120 s, httpx 60 s per phase -> a second worker paid again."""
    make = sessionmaker(bind=ledger_engine)
    second_spy = Spy()
    answers = []
    # Declares a 0.1 s deadline but ignores it (a stalled process): the
    # lease (1 s margin -> 2 s) expires while the paid call is still running.
    slow = Spy(delay=0.0, total_timeout_seconds=0.1)

    def second_worker_after_expiry():
        time.sleep(2.2)
        other = SharedFirecrawlFederationService(make(), mapper=second_spy)
        answers.append(_map(other, module="matrix"))

    slow.during_call = second_worker_after_expiry
    first = SharedFirecrawlFederationService(
        make(), mapper=slow, lease_margin_seconds=1
    )
    status, profile = _map(first)

    assert answers == [("review_required", None)]
    assert second_spy.calls == []
    # Nobody else was authorised, so the original holder's late result lands.
    assert status == "fetched" and profile is not None
    row = _row(ledger_engine)
    assert (row.status, row.credits_spent) == ("complete", 1)
    assert len(slow.calls) == 1


@LEDGER_BACKENDS
def test_post_pay_ledger_outage_never_re_pays_on_lease_expiry(ledger_engine):
    """The paid call succeeds, then every ledger write fails (DB unreachable)."""
    make = sessionmaker(bind=ledger_engine)
    spy = Spy()
    service = SharedFirecrawlFederationService(make(), mapper=spy)
    service.ledger.complete = Mock(side_effect=RuntimeError("ledger down"))
    service.ledger.hold_for_review = Mock(side_effect=RuntimeError("ledger down"))
    with pytest.raises(PaidResultUnrecordedError) as excinfo:
        _map(service)
    assert excinfo.value.held_for_review is False
    row = _row(ledger_engine)
    assert row.status == "leased"  # nothing could be written

    # Let the lease expire, then every later worker (and a forced refresh)
    # is refused: the paid outcome is unrecorded, so no silent re-pay.
    session = make()
    stored = session.query(AcquisitionLedgerRow).one()
    stored.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session.commit()
    for module in ("matrix", "atlas"):
        again = SharedFirecrawlFederationService(make(), mapper=spy)
        assert _map(again, module=module)[0] == "review_required"
    again = SharedFirecrawlFederationService(make(), mapper=spy)
    assert (
        _map(again, force_refresh=True, operator_override="op")[0] == "review_required"
    )
    assert len(spy.calls) == 1

    # An explicit operator release re-opens it for exactly one paid call.
    ledger = AcquisitionLedger(make())
    assert ledger.release_for_retry(
        stored.resource_key, operator_id="op-7", reason="confirmed with provider"
    )
    assert _map(SharedFirecrawlFederationService(make(), mapper=spy))[0] == "fetched"
    assert _map(SharedFirecrawlFederationService(make(), mapper=spy))[0] == (
        "cache_hit"
    )
    assert len(spy.calls) == 2


@LEDGER_BACKENDS
def test_lease_that_lapsed_before_the_call_is_released_not_spent(ledger_engine):
    make = sessionmaker(bind=ledger_engine)
    spy = Spy()
    service = SharedFirecrawlFederationService(make(), mapper=spy)
    real = service.ledger.assert_lease_live

    def lapsed(lease, **kwargs):
        # Expire our own lease, then run the real pre-call check.
        session = make()
        row = session.query(AcquisitionLedgerRow).one()
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
        session.close()
        return real(lease, **kwargs)

    service.ledger.assert_lease_live = lapsed
    assert _map(service) == ("stale_lease", None)
    assert spy.calls == []
    row = _row(ledger_engine)
    assert row.status == "failed" and row.credits_spent == 0


@LEDGER_BACKENDS
def test_unbuildable_paid_result_is_held_for_review(ledger_engine):
    make = sessionmaker(bind=ledger_engine)
    spy = Spy()
    spy_profile = spy.map_source

    def broken(**kwargs):
        profile = spy_profile(**kwargs)
        return SimpleNamespace(to_dict=lambda: {"unserialisable": object()}, p=profile)

    mapper = SimpleNamespace(map_source=broken)
    service = SharedFirecrawlFederationService(make(), mapper=mapper)
    with pytest.raises(PaidResultUnrecordedError) as excinfo:
        _map(service)
    assert excinfo.value.held_for_review is True
    row = _row(ledger_engine)
    assert (row.status, row.credits_spent, row.failure_count) == (
        "review_required",
        1,
        0,
    )
    assert json.loads(row.provenance_json)["review_reason"].startswith(
        "result_not_recorded:"
    )
    assert _map(SharedFirecrawlFederationService(make(), mapper=spy))[0] == (
        "review_required"
    )
    assert len(spy.calls) == 1


# --- 3. Coverage keying: limit / sitemap do not buy a second map --------------


@LEDGER_BACKENDS
def test_limit_and_sitemap_variations_pay_only_when_justified(ledger_engine, caplog):
    caplog.set_level(logging.WARNING, logger="app.federation.shared_firecrawl")
    make = sessionmaker(bind=ledger_engine)
    spy = Spy()

    def run(**overrides):
        return _map(SharedFirecrawlFederationService(make(), mapper=spy), **overrides)

    # Documented sequence, no override: exactly ONE paid call.
    assert run(limit=50)[0] == "fetched"
    assert run(limit=51) == ("coverage_insufficient", None)
    assert run(limit=50, sitemap="skip") == ("coverage_insufficient", None)
    assert run(limit=50)[0] == "cache_hit"
    assert run(limit=25)[0] == "cache_hit"  # a smaller request is covered
    assert len(spy.calls) == 1
    assert run(force_refresh=True) == ("override_required", None)
    assert len(spy.calls) == 1

    # With an explicit, logged operator override on the 51: exactly TWO.
    assert run(limit=51, operator_override="op-1")[0] == "fetched"
    assert len(spy.calls) == 2 and spy.calls[-1]["limit"] == 51
    assert run(limit=50)[0] == "cache_hit"  # covered by the stored 51
    assert run(limit=51)[0] == "cache_hit"
    assert run(limit=50, sitemap="skip") == ("coverage_insufficient", None)
    assert len(spy.calls) == 2
    overrides = [r.getMessage() for r in caplog.records if "override" in r.msg]
    assert len(overrides) == 1 and "operator=op-1" in overrides[0]
    # One canonical resource, one row.
    row = _row(ledger_engine)
    assert row.credits_spent == 2
    assert json.loads(row.provenance_json)["map_limit"] == "51"


@LEDGER_BACKENDS
def test_legacy_parameter_keyed_row_is_still_reused(ledger_engine):
    make = sessionmaker(bind=ledger_engine)
    ledger = AcquisitionLedger(make())
    legacy = SharedFirecrawlFederationService.legacy_acquisition_request(
        consumer_module="pre-upgrade",
        root_url=POWO,
        search="Phragmipedium",
        limit=50,
        sitemap="include",
        include_subdomains=False,
    )
    lease = ledger.claim(legacy, worker_id="old")
    payload = json.dumps(
        build_source_profile(
            source_id="powo", root_url=POWO, urls=(POWO + "taxon/x",)
        ).to_dict(),
        sort_keys=True,
    )
    ledger.complete(
        AcquisitionRecord.completed(
            request=legacy,
            content=payload.encode(),
            provenance={"retrieval_method": "firecrawl_map"},
            credits_spent=1,
        ),
        lease=lease,
        payload_json=payload,
    )
    spy = Spy()
    status, profile = _map(SharedFirecrawlFederationService(make(), mapper=spy))
    assert status == "cache_hit" and profile.urls == (POWO + "taxon/x",)
    assert spy.calls == []


def test_equal_resource_different_parameters_share_one_key():
    key = SharedFirecrawlFederationService.acquisition_request
    base = key(consumer_module="a", root_url=POWO, search="Phragmipedium")
    assert (
        key(
            consumer_module="b",
            root_url="https://POWO.science.kew.org:443/?utm_source=x",
            search="Phragmipedium",
            limit=999,
            sitemap="skip",
        ).key
        == base.key
    )
    assert key(consumer_module="a", root_url=POWO, search="Masdevallia").key != (
        base.key
    )
    assert (
        key(
            consumer_module="a",
            root_url=POWO,
            search="Phragmipedium",
            include_subdomains=True,
        ).key
        != base.key
    )


# --- 4. One canonicaliser for the ledger key and held-corpus matching ---------


URL_PAIRS = [
    # (a, b, same resource?)
    ("https://example.org/taxon/", "https://example.org/taxon", True),
    ("https://example.org", "https://example.org/", True),
    ("https://Example.ORG./taxon", "https://example.org/taxon", True),
    ("https://example.org:443/taxon", "https://example.org/taxon", True),
    ("https://example.org/taxon#frag", "https://example.org/taxon", True),
    (
        "https://example.org/t?utm_source=x&b=2&a=1",
        "https://example.org/t?a=1&b=2",
        True,
    ),
    ("https://example.org/t?a=", "https://example.org/t?a", True),
    # Deliberately distinct: different origins (see acquisition.py).
    ("http://example.org/taxon", "https://example.org/taxon", False),
    ("https://www.example.org/taxon", "https://example.org/taxon", False),
    ("https://example.org:8443/taxon", "https://example.org/taxon", False),
    ("https://example.org/Taxon", "https://example.org/taxon", False),
    ("https://example.org/t?a=1", "https://example.org/t?a=2", False),
]


@pytest.mark.parametrize(("left", "right", "same"), URL_PAIRS)
def test_ledger_key_and_held_match_agree(left, right, same):
    keys_equal = resource_key(url=left, provider="p") == resource_key(
        url=right, provider="p"
    )
    held = held_source_match({"source_url": left}, [{"source_url": right}])
    assert keys_equal is same
    assert held is same
    assert (canonicalize_url(left) == canonicalize_url(right)) is same


def test_non_http_and_blank_urls_never_match_by_canonicalisation():
    assert held_source_match({"source_url": "urn:x:1"}, [{"source_url": "urn:x:1"}])
    assert not held_source_match({"source_url": "urn:x:1"}, [{"source_url": "urn:x:2"}])
    assert not held_source_match({"source_url": "   "}, [{"source_url": "   "}])
    assert not held_source_match({"source_url": None}, [{"source_url": None}])
    assert canonicalize_url("https://example.org//") == "https://example.org/"


# --- 2. Pilot gate parity: the provider's own gate and budget reservation ------


def _pilot_env(**changes):
    env = dict(LIVE_ENV)
    for name, value in changes.items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    return env


def test_pilot_reuses_the_provider_gate_and_reservation_functions():
    assert federation_pilot.live_gate is firecrawl_provider.live_gate
    assert (
        federation_pilot.reserve_live_attempt is firecrawl_provider.reserve_live_attempt
    )


GATE_CASES = [
    ({}, None),
    ({"FIRECRAWL_ENABLED": None}, "FIRECRAWL_DISABLED"),
    ({"FIRECRAWL_KILL_SWITCH": "true"}, "FIRECRAWL_DISABLED"),
    ({"FIRECRAWL_DRY_RUN": None}, "DRY_RUN_NO_FIXTURE"),
    ({"PROVIDER_AUTHORIZED": None}, "PROVIDER_NOT_AUTHORIZED"),
    ({"PROVIDER_AUTHORIZED": "yes"}, "PROVIDER_NOT_AUTHORIZED"),
    ({"NO_API_MODE": None}, "PROVIDER_NOT_AUTHORIZED"),
    ({"FIRECRAWL_API_KEY": None}, "FIRECRAWL_KEY_UNAVAILABLE"),
    ({"FIRECRAWL_MAX_CALL_COST_USD": "0"}, "DURABLE_BUDGET_AUTHORITY_REQUIRED"),
    ({"FIRECRAWL_DAILY_BUDGET_USD": None}, "DURABLE_BUDGET_AUTHORITY_REQUIRED"),
    ({"FIRECRAWL_ENABLED": "maybe"}, "INVALID_FLAG"),
    ({"FIRECRAWL_MAX_CALL_COST_USD": "lots"}, "INVALID_CONFIG"),
]


@pytest.mark.parametrize(("changes", "expected"), GATE_CASES)
def test_pilot_gate_matches_the_provider_gate(changes, expected):
    env = _pilot_env(**changes)
    authority = FakeSpendAuthority().authority()
    assert provider_gate(env, authority=authority, lease_check=lambda: None) == expected
    try:
        config = FirecrawlConfig.from_env(env)
    except AcquisitionBlocked as exc:
        provider_code = str(exc)
    except Exception:  # noqa: BLE001 - the pilot maps these to INVALID_CONFIG
        provider_code = "INVALID_CONFIG"
    else:
        provider = FirecrawlProvider(
            config,
            governor=authority.governor,
            reserve=authority.reserve,
            reserve_credits=authority.reserve_credits,
            observe_credits=authority.observe_credits,
            env=env,
        )
        provider.lease_check = lambda: None
        try:
            provider._gate()
            provider_code = None
        except AcquisitionBlocked as exc:
            provider_code = str(exc)
    assert provider_code == expected


def test_pilot_gate_without_budget_authority_is_blocked():
    assert provider_gate(_pilot_env(), authority=None, lease_check=lambda: None) == (
        "DURABLE_BUDGET_AUTHORITY_REQUIRED"
    )
    authority = FakeSpendAuthority().authority()
    assert provider_gate(_pilot_env(), authority=authority, lease_check=None) == (
        "DURABLE_BUDGET_AUTHORITY_REQUIRED"
    )


def _pilot(engine, spy, spend, env=None, **kwargs):
    session = sessionmaker(bind=engine)()
    try:
        return run_pilot(
            session=session,
            sources={"powo": pilot_script.SOURCES["powo"]},
            mapper=spy,
            holdings=CorpusHoldings(None, audit=_synthetic_audit()),
            env=env or dict(LIVE_ENV),
            authority=spend.authority() if spend is not None else None,
            **kwargs,
        )
    finally:
        session.close()


@LEDGER_BACKENDS
@pytest.mark.parametrize(("changes", "expected"), GATE_CASES[1:])
def test_blocked_pilot_gate_takes_no_lease_and_reserves_nothing(
    ledger_engine, changes, expected
):
    spy, spend = Spy(), FakeSpendAuthority()
    report = _pilot(ledger_engine, spy, spend, env=_pilot_env(**changes))
    assert [s["status"] for s in report.sources] == ["blocked"]
    assert report.sources[0]["reason"] == expected
    assert spy.calls == [] and report.provider_calls == 0
    assert spend.credit_reservations == spend.usd_reservations == []
    session = sessionmaker(bind=ledger_engine)()
    assert session.query(AcquisitionLedgerRow).count() == 0
    session.close()


@LEDGER_BACKENDS
def test_pilot_reserves_budget_before_the_paid_call_and_only_then(ledger_engine):
    spy, spend = Spy(), FakeSpendAuthority()
    first = _pilot(ledger_engine, spy, spend)
    second = _pilot(ledger_engine, spy, spend)
    assert [s["status"] for s in first.sources] == ["fetched"]
    assert [s["status"] for s in second.sources] == ["cache_hit"]
    assert len(spy.calls) == 1
    # One paid call, one reservation each (credit tariff 1, daily cap 25).
    assert [(amount, cap) for _t, amount, cap in spend.credit_reservations] == [(1, 25)]
    assert len(spend.usd_reservations) == 1
    assert spend.observations == [None]  # Map reports no usage: stays unknown
    assert spend.ended == [True]


@LEDGER_BACKENDS
def test_refused_reservation_makes_no_paid_call(ledger_engine):
    spy, spend = Spy(), FakeSpendAuthority(refuse_credits=True)
    report = _pilot(ledger_engine, spy, spend)
    assert report.sources[0]["status"] == "blocked"
    assert report.sources[0]["reason"] == "DURABLE_RESERVATION_FAILED"
    assert spy.calls == [] and report.provider_calls == 0
    row = _row(ledger_engine)
    assert row.status == "failed"  # lease released, retry window open
    again = _pilot(ledger_engine, spy, FakeSpendAuthority())
    assert again.sources[0]["status"] == "retry_blocked"
    assert spy.calls == []


def test_pilot_script_coverage_and_override(monkeypatch, tmp_path):
    from sqlalchemy import create_engine

    from app.database import Base

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
        pilot_script, "build_spend_authority", lambda _u, _e: spend.authority()
    )
    monkeypatch.setattr(
        pilot_script,
        "build_holdings_check",
        lambda _u: CorpusHoldings(None, audit=_synthetic_audit()),
    )
    spy = Spy()
    monkeypatch.setattr(
        FirecrawlFederationMapper, "map_source", lambda self, **kw: spy.map_source(**kw)
    )

    def run(*args, tag):
        out = tmp_path / f"{tag}.json"
        monkeypatch.setattr(
            sys, "argv", ["pilot", "--source", "powo", *args, "--output", str(out)]
        )
        code = pilot_script.main()
        return code, json.loads(out.read_text())["sources"][0]["status"]

    assert run("--limit", "50", tag="a") == (0, "fetched")
    assert run("--limit", "51", tag="b") == (3, "coverage_insufficient")
    assert run("--sitemap", "skip", tag="c") == (3, "coverage_insufficient")
    assert run("--limit", "50", tag="d") == (0, "cache_hit")
    assert len(spy.calls) == 1
    assert run("--limit", "51", "--operator-override", "op-2", tag="e") == (
        0,
        "fetched",
    )
    assert len(spy.calls) == 2 and len(spend.credit_reservations) == 2


def test_held_trailing_slash_variant_blocks_the_paid_map(ledger_engine):
    spy, spend = Spy(), FakeSpendAuthority()
    session = sessionmaker(bind=ledger_engine)()
    report = run_pilot(
        session=session,
        sources={
            "sub": {
                "source_id": "powo_taxon",
                "root_url": "https://powo.science.kew.org/taxon/",
                "search": "Phragmipedium",
            }
        },
        mapper=spy,
        holdings=CorpusHoldings(
            None,
            audit=_synthetic_audit(
                [{"source_url": "https://powo.science.kew.org/taxon", "doi": ""}]
            ),
        ),
        env=dict(LIVE_ENV),
        authority=spend.authority(),
    )
    session.close()
    assert [s["status"] for s in report.sources] == ["already_held"]
    assert spy.calls == [] and spend.credit_reservations == []
