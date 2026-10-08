"""Paid Firecrawl searches go through the acquisition ledger (/acquisition/execute).

Provider-free. Live-mode searches reach only an ``httpx.MockTransport``
installed in place of ``httpx.Client``; the real httpx transport and Python
socket connects fail the test and are counted (0 real calls asserted after
every test). Search results are synthetic shapes, not captured provider data.
"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.literature_extraction.firecrawl_acquisition import acquire_matrix_sources
from app.literature_extraction.firecrawl_provider import (
    AcquisitionBlocked,
    FirecrawlConfig,
    FirecrawlProvider,
)
from app.literature_extraction.firecrawl_search_cache import (
    LedgerSearchCache,
    search_request,
)
from app.source_federation.acquisition_ledger import AcquisitionLedger
from app.source_federation.acquisition_models import AcquisitionLedgerRow
from app.source_federation.deadline import lease_seconds_for
from tests.acquisition_ledger_backends import migrated_postgres_engine

LIVE_ENV = {
    "PROVIDER_AUTHORIZED": "true",
    "NO_API_MODE": "false",
    "FIRECRAWL_API_KEY": "test-placeholder-not-a-credential",
}
URL = "https://flora.example/monograph"


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
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


class MockFirecrawl:
    """``httpx.MockTransport`` behind ``httpx.Client``; counts by endpoint."""

    def __init__(self, monkeypatch, *, delay=0.0, statuses=()):
        self.delay = delay
        self.statuses = list(statuses)
        self.calls: list[str] = []
        self.observed = []
        self.during = None
        self._lock = threading.Lock()
        client = httpx.Client

        def handler(request):
            with self._lock:
                self.calls.append(request.url.path.rsplit("/", 1)[-1])
                status = self.statuses.pop(0) if self.statuses else 200
            if self.during is not None:
                self.during()
            time.sleep(self.delay)
            if status != 200:
                return httpx.Response(status)
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "creditsUsed": 2,
                    "data": {"web": [{"url": URL, "doi": "10.1234/synthetic"}]},
                },
            )

        monkeypatch.setattr(
            httpx,
            "Client",
            lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs),
        )


@pytest.fixture(
    params=[
        "sqlite_file",
        pytest.param("postgres_migrated", marks=pytest.mark.requires_postgres),
    ]
)
def engine(request, tmp_path):
    if request.param == "sqlite_file":
        engine = create_engine(f"sqlite:///{tmp_path / 'ledger.sqlite3'}")
        Base.metadata.create_all(engine, tables=[AcquisitionLedgerRow.__table__])
        try:
            yield engine
        finally:
            engine.dispose()
        return
    with migrated_postgres_engine(pool_size=10) as engine:
        yield engine


def _config(**changes):
    return replace(
        FirecrawlConfig(
            enabled=True,
            dry_run=False,
            domains=("flora.example", "orchids.example"),
            max_call_cost=Decimal("0.01"),
            daily_budget=Decimal(1),
        ),
        **changes,
    )


def _provider(engine, *, config=None, clock=None, cache=True):
    reservations: list[int] = []
    provider = FirecrawlProvider(
        config or _config(),
        governor=SimpleNamespace(
            begin=lambda request: object(), end=lambda *a, **k: None
        ),
        reserve=lambda *args: None,
        reserve_credits=lambda task, amount, cap: (
            reservations.append(amount) or {"reserved": amount}
        ),
        observe_credits=lambda reservation, used: None,
        sleep=lambda seconds: None,
        env=LIVE_ENV,
        search_cache=(
            LedgerSearchCache(
                sessionmaker(bind=engine),
                freshness_seconds=3600,
                poll_seconds=0.05,
                clock=clock,
            )
            if cache
            else None
        ),
    )
    provider.lease_check = lambda: None
    provider.test_reservations = reservations
    return provider


def _rows(engine):
    session = sessionmaker(bind=engine)()
    try:
        return session.query(AcquisitionLedgerRow).all()
    finally:
        session.close()


def test_repeated_execution_of_the_same_gap_pays_once(monkeypatch, engine):
    firecrawl = MockFirecrawl(monkeypatch)
    first = _provider(engine)
    urls = first.search("Paphiopedilum", task_id="gap-1")
    # A new execution: new provider, new lease, new process as far as the
    # provider knows. Before: _request("search") ran again (2 more credits).
    second = _provider(engine)
    again = second.search("Paphiopedilum", task_id="gap-1-retry")

    assert again == urls == [URL]
    assert firecrawl.calls == ["search"]
    assert first.credits_reserved == 2 and second.credits_reserved == 0
    assert second.test_reservations == [] and second.calls == 0
    assert second.search_cache_hits == 1
    # Search metadata (incl. DOI) is restored for the pre-scrape held check.
    assert second.search_results[URL]["doi"] == "10.1234/synthetic"
    (row,) = _rows(engine)
    assert (row.status, row.credits_spent, row.provider) == (
        "complete",
        2,
        "firecrawl_search",
    )


def test_domain_order_and_whitespace_do_not_create_a_new_paid_search(
    monkeypatch, engine
):
    firecrawl = MockFirecrawl(monkeypatch)
    _provider(engine).search("Paphiopedilum", task_id="a")
    reordered = _provider(
        engine, config=_config(domains=("orchids.example", "flora.example"))
    )
    reordered.search("Paphiopedilum", task_id="b")
    assert firecrawl.calls == ["search"]
    assert reordered.search_cache_hits == 1
    payload = {"query": "a  b\n c", "limit": 2}
    assert (
        search_request(payload, consumer="x").key
        == search_request({"query": "a b c", "limit": 2}, consumer="y").key
    )
    assert (
        search_request(payload, consumer="x").key
        != search_request({"query": "a b c", "limit": 3}, consumer="x").key
    )


def test_a_different_gap_is_a_different_paid_search(monkeypatch, engine):
    firecrawl = MockFirecrawl(monkeypatch)
    _provider(engine).search("Paphiopedilum", task_id="a")
    _provider(engine).search(
        "Paphiopedilum", task_id="b", target_names=("Paphiopedilum delenatii",)
    )
    assert firecrawl.calls == ["search", "search"]


def test_result_older_than_the_freshness_window_is_refreshed_through_the_lease(
    monkeypatch, engine
):
    firecrawl = MockFirecrawl(monkeypatch)
    start = datetime.now(timezone.utc)
    _provider(engine, clock=lambda: start).search("Paphiopedilum", task_id="a")
    within = _provider(engine, clock=lambda: start + timedelta(seconds=3599))
    within.search("Paphiopedilum", task_id="b")
    assert firecrawl.calls == ["search"]
    later = start + timedelta(seconds=3601)
    _provider(engine, clock=lambda: later).search("Paphiopedilum", task_id="c")
    assert firecrawl.calls == ["search", "search"]
    _provider(engine, clock=lambda: later).search("Paphiopedilum", task_id="d")
    assert firecrawl.calls == ["search", "search"]
    (row,) = _rows(engine)
    assert row.credits_spent == 4


def test_concurrent_executions_of_one_gap_make_one_search_call(monkeypatch, engine):
    firecrawl = MockFirecrawl(monkeypatch, delay=0.4)
    count = 6
    barrier = threading.Barrier(count)
    results: list = [None] * count
    errors: list = []

    def worker(index):
        try:
            provider = _provider(engine)
            barrier.wait(timeout=10)
            results[index] = (
                provider.search("Paphiopedilum", task_id=f"t{index}"),
                provider.credits_reserved,
            )
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not errors, errors
    assert firecrawl.calls == ["search"]
    assert {tuple(urls) for urls, _credits in results} == {(URL,)}
    assert sorted(credits for _urls, credits in results) == [0] * (count - 1) + [2]


def test_live_search_without_the_ledger_is_refused(monkeypatch, engine):
    firecrawl = MockFirecrawl(monkeypatch)
    provider = _provider(engine, cache=False)
    with pytest.raises(AcquisitionBlocked, match="SEARCH_LEDGER_REQUIRED"):
        provider.search("Paphiopedilum", task_id="a")
    assert firecrawl.calls == [] and provider.credits_reserved == 0


def test_missing_ledger_table_fails_closed(monkeypatch, tmp_path):
    firecrawl = MockFirecrawl(monkeypatch)
    bare = create_engine(f"sqlite:///{tmp_path / 'bare.sqlite3'}")
    provider = _provider(bare)
    with pytest.raises(AcquisitionBlocked, match="ACQUISITION_LEDGER_UNAVAILABLE"):
        provider.search("Paphiopedilum", task_id="a")
    assert firecrawl.calls == [] and provider.credits_reserved == 0
    bare.dispose()


def test_unrecordable_paid_search_is_held_for_review(monkeypatch, engine):
    firecrawl = MockFirecrawl(monkeypatch)

    def refuse(self, *args, **kwargs):
        raise RuntimeError("ledger write failed (synthetic)")

    with monkeypatch.context() as patch:
        patch.setattr(AcquisitionLedger, "complete", refuse)
        with pytest.raises(AcquisitionBlocked, match="SEARCH_RESULT_UNRECORDED"):
            _provider(engine).search("Paphiopedilum", task_id="a")
    (row,) = _rows(engine)
    assert (row.status, row.credits_spent) == ("review_required", 2)
    with pytest.raises(AcquisitionBlocked, match="SEARCH_REVIEW_REQUIRED"):
        _provider(engine).search("Paphiopedilum", task_id="b")
    assert firecrawl.calls == ["search"]


def test_failed_paid_search_opens_a_retry_window_not_a_retry_storm(monkeypatch, engine):
    firecrawl = MockFirecrawl(monkeypatch, statuses=[503, 503, 503])
    with pytest.raises(AcquisitionBlocked, match="RETRIES_EXHAUSTED"):
        _provider(engine).search("Paphiopedilum", task_id="a")
    assert firecrawl.calls == ["search"] * 3
    with pytest.raises(AcquisitionBlocked, match="SEARCH_RETRY_BLOCKED"):
        _provider(engine).search("Paphiopedilum", task_id="b")
    assert len(firecrawl.calls) == 3


def test_each_attempt_has_a_wall_clock_deadline_and_the_lease_covers_all(
    monkeypatch, engine
):
    config = _config(request_timeout_seconds=1, retry_cap=0)
    assert config.max_request_wall_seconds() == 1.0
    defaults = _config()
    assert defaults.max_request_wall_seconds() == 3 * 45 + 1 + 2
    assert lease_seconds_for(defaults.max_request_wall_seconds()) == 198

    firecrawl = MockFirecrawl(monkeypatch, delay=2.5)
    make = sessionmaker(bind=engine)
    seen = []

    def lease_during_call():
        session = make()
        try:
            row = session.query(AcquisitionLedgerRow).one()
            expires = row.lease_expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            seen.append(expires - datetime.now(timezone.utc))
        finally:
            session.close()

    firecrawl.during = lease_during_call
    started = time.monotonic()
    with pytest.raises(AcquisitionBlocked, match="PROVIDER_DEADLINE_EXCEEDED"):
        _provider(engine, config=config).search("Paphiopedilum", task_id="a")
    assert time.monotonic() - started < 2.4
    # The lease outlives the whole bounded request by the margin.
    assert seen and seen[0] > timedelta(seconds=config.max_request_wall_seconds())
    (row,) = _rows(engine)
    assert row.status == "failed" and row.lease_expires_at is None


# --- held-corpus check before any paid scrape ---------------------------------


def _services(tmp_path):
    from tests.test_firecrawl_corpus_first import services

    return services(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "held",
    [
        {"doi": "10.1234/SYNTHETIC", "source_url": "https://elsewhere.example/x"},
        {"source_url": URL + "/"},
        {"source_url": "https://FLORA.example:443/monograph?utm_source=feed"},
    ],
)
async def test_held_document_by_doi_or_canonical_url_is_never_scraped(tmp_path, held):
    calls = []

    def transport(endpoint, payload):
        calls.append(endpoint)
        if endpoint == "search":
            return 200, {
                "success": True,
                "data": {"web": [{"url": URL, "doi": "10.1234/synthetic"}]},
            }
        raise AssertionError("a held document must not be scraped")

    provider = FirecrawlProvider(
        FirecrawlConfig(enabled=True, domains=("flora.example",)),
        fixture_transport=transport,
    )
    with pytest.raises(AcquisitionBlocked, match="NO_TRACEABLE_MORPHOLOGY_EVIDENCE"):
        await acquire_matrix_sources(
            **_services(tmp_path),
            provider=provider,
            corpus_audit=lambda: {
                "available": True,
                "complete": True,
                "documents": [],
                "identities": [held],
            },
            load_held_source=lambda document: None,
            target_names=("Paphiopedilum delenatii",),
            required_predicates=("leaf_length",),
        )
    assert calls == ["search"]
    assert provider.documents == 0


def test_runtime_composes_the_ledger_search_cache(monkeypatch, tmp_path):
    from app.literature_extraction import firecrawl_runtime as runtime

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    with pytest.raises(AcquisitionBlocked, match="ACQUISITION_DATABASE_REQUIRED"):
        runtime.search_cache(FirecrawlConfig())
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'r.sqlite3'}")
    cache = runtime.search_cache(FirecrawlConfig(search_cache_seconds=60))
    assert isinstance(cache, LedgerSearchCache)
    assert cache.freshness == timedelta(seconds=60)
    for bad in (0, 30 * 24 * 3600 + 1, True):
        with pytest.raises(AcquisitionBlocked, match="INVALID_SEARCH_CACHE_WINDOW"):
            FirecrawlConfig(search_cache_seconds=bad)
    for bad in (0.5, 121, True):
        with pytest.raises(AcquisitionBlocked, match="INVALID_REQUEST_TIMEOUT"):
            FirecrawlConfig(request_timeout_seconds=bad)
