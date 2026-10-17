"""Credit admission never substitutes estimated reservations for actual usage."""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.literature_extraction.firecrawl_provider import (
    AcquisitionBlocked,
    FirecrawlConfig,
    FirecrawlProvider,
)


@pytest.mark.parametrize("cap", [0, -1, 26, True, 1.5])
def test_credit_cap_cannot_be_increased_or_disabled(cap):
    with pytest.raises(AcquisitionBlocked, match="INVALID_DAILY_CREDIT_CAP"):
        FirecrawlConfig(daily_credit_cap=cap)


def test_credit_defaults_and_tariffs():
    assert FirecrawlConfig.from_env({}).daily_credit_cap == 25
    for limit, expected in [(1, 2), (10, 2), (11, 4), (100, 20)]:
        assert (
            FirecrawlProvider.credit_cost("search", {"query": "orchid", "limit": limit})
            == expected
        )
    payload = {
        "url": "https://example.org/",
        "formats": ["markdown"],
        "parsers": [],
        "proxy": "basic",
        "onlyMainContent": True,
    }
    assert (
        FirecrawlProvider.credit_cost("scrape", payload) == 3
    )  # possible team threat protection
    for override in [
        {"formats": ["json"]},
        {"proxy": "auto"},
        {"parsers": ["pdf"]},
        {"actions": []},
    ]:
        with pytest.raises(AcquisitionBlocked, match="UNBOUNDED_CREDIT_OPTIONS"):
            FirecrawlProvider.credit_cost("scrape", {**payload, **override})
    with pytest.raises(AcquisitionBlocked):
        FirecrawlProvider.credit_cost(
            "search", {"query": "orchid", "limit": 2, "scrapeOptions": {}}
        )


def test_live_requires_durable_credit_authority_even_with_usd_budget():
    config = replace(
        FirecrawlConfig(),
        enabled=True,
        dry_run=False,
        max_call_cost=Decimal(1),
        daily_budget=Decimal(10),
    )
    provider = FirecrawlProvider(
        config,
        governor=object(),
        reserve=lambda *args: None,
        env={
            "PROVIDER_AUTHORIZED": "true",
            "NO_API_MODE": "false",
            "FIRECRAWL_API_KEY": "synthetic-test-key",
        },
    )
    provider.lease_check = lambda: None
    with pytest.raises(AcquisitionBlocked, match="DURABLE_BUDGET_AUTHORITY_REQUIRED"):
        provider._gate()


def test_unknown_usage_is_not_reported_as_actual():
    provider = FirecrawlProvider(FirecrawlConfig())
    assert provider.credit_receipt()["provider_reported"] is None
    assert provider.credit_receipt()["usage_complete"] is False
    provider.credits_reserved, provider.calls = 3, 1
    assert provider.credit_receipt()["provider_reported"] is None
    provider.reported_credits, provider.usage_reports = 1, 1
    provider.config = replace(provider.config, dry_run=False)
    assert provider.credit_receipt() == {
        "reserved": 3,
        "daily_cap": 25,
        "provider_reported": 1,
        "reported_attempts": 1,
        "attempts": 1,
        "usage_complete": True,
    }


def _memory_search_cache():
    """A ledger search cache on a private in-memory SQLite ledger."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import Base
    from app.literature_extraction.firecrawl_search_cache import LedgerSearchCache
    from app.source_federation.acquisition_models import AcquisitionLedgerRow

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[AcquisitionLedgerRow.__table__])
    return LedgerSearchCache(sessionmaker(bind=engine), freshness_seconds=3600)


def test_retry_attempts_are_reserved_and_unknown_usage_stays_unknown(monkeypatch):
    from types import SimpleNamespace

    import httpx

    calls, reservations, observations = [], [], []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(
            200, json={"success": True, "data": {"web": []}, "creditsUsed": 2}
        )

    client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs),
    )

    def reserve(task, amount, cap):
        reservations.append(amount)
        return {"reserved": amount}

    provider = FirecrawlProvider(
        FirecrawlConfig(
            enabled=True,
            dry_run=False,
            domains=("example.org",),
            max_call_cost=Decimal(1),
            daily_budget=Decimal(10),
        ),
        governor=SimpleNamespace(
            begin=lambda request: object(), end=lambda *args, **kwargs: None
        ),
        reserve=lambda *args: None,
        reserve_credits=reserve,
        observe_credits=lambda token, used: observations.append(used),
        sleep=lambda duration: None,
        env={
            "PROVIDER_AUTHORIZED": "true",
            "NO_API_MODE": "false",
            "FIRECRAWL_API_KEY": "synthetic-test-key",
        },
        search_cache=_memory_search_cache(),
    )
    provider.lease_check = lambda: None
    assert provider.search("Paphiopedilum", task_id="fixture") == []
    assert reservations == [2, 2]
    assert observations == [None, 2]
    assert provider.credit_receipt()["reserved"] == 4
    assert provider.credit_receipt()["provider_reported"] == 2
    assert provider.credit_receipt()["usage_complete"] is False
    provider.reserve_credits = lambda *args: (_ for _ in ()).throw(
        AcquisitionBlocked("DAILY_CREDIT_CAP")
    )
    provider.searches = 0
    # A fresh ledger, so the repeat is not answered from the stored result.
    provider.search_cache = _memory_search_cache()
    with pytest.raises(AcquisitionBlocked, match="DURABLE_RESERVATION_FAILED"):
        provider.search("Paphiopedilum", task_id="fixture")
    assert len(calls) == 2


@pytest.mark.requires_postgres
def test_persistent_credit_cap_serializes_concurrent_workers(monkeypatch):
    import os
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from uuid import uuid4

    import psycopg

    from app.literature_extraction.firecrawl_provider import (
        PostgresFirecrawlReservation,
    )
    from runtime import research_station_store

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL required for isolated PostgreSQL credit proof")
    schema = "firecrawl_credit_test_" + uuid4().hex
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations/CALYX-RECOVERY-001-research-station-records.sql"
    ).read_text()
    with psycopg.connect(url) as conn:
        conn.execute(migration.replace("oc_admin", schema))
    monkeypatch.setattr(
        research_station_store, "TABLE", f"{schema}.research_station_records"
    )
    ledger = PostgresFirecrawlReservation(lambda: psycopg.connect(url))
    try:

        def attempt(number):
            try:
                return ledger.reserve_credits(f"credit-test-{number}", 2, 25)
            except AcquisitionBlocked as exc:
                assert str(exc) == "DAILY_CREDIT_CAP"
                return None

        with ThreadPoolExecutor(max_workers=8) as workers:
            reservations = [item for item in workers.map(attempt, range(20)) if item]
        assert len(reservations) == 12
        final = ledger.reserve_credits("last-credit", 1, 25)
        with pytest.raises(AcquisitionBlocked, match="DAILY_CREDIT_CAP"):
            ledger.reserve_credits("over-cap", 1, 25)
        ledger.observe_credits(reservations[0], 1)
        ledger.observe_credits(final, None)
        ledger("usd-preserved", Decimal("0.01"), Decimal(1))
        with psycopg.connect(url) as conn:
            payload = conn.execute(
                f"SELECT payload FROM {schema}.research_station_records"
            ).fetchone()[0]
        assert payload["reserved_credits"] == 25
        assert payload["credit_reservations"] == 13
        assert payload["provider_reported_credits"] == 1
        assert payload["credit_usage_reports"] == 1
        assert payload["reserved_usd"] == "0.01"

        # A new process/lease cannot reuse the one-live-acquisition authority.
        from app.literature_extraction import firecrawl_runtime as runtime

        monkeypatch.setattr(runtime, "connection", lambda: psycopg.connect(url))
        request = runtime.AcquisitionRequest(
            issue_number=123, run_id=77, run_attempt=1, comment_id=100
        )
        runtime.reserve_live_pilot_attempt(request)
        later_lease = request.model_copy(update={"run_id": 78, "comment_id": 101})
        with pytest.raises(AcquisitionBlocked, match="LIVE_PILOT_ALREADY_ATTEMPTED"):
            runtime.reserve_live_pilot_attempt(later_lease)
    finally:
        from psycopg import sql

        with psycopg.connect(url) as conn:
            conn.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )
