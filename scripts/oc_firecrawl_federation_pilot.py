#!/usr/bin/env python3
"""Run a bounded Firecrawl federation reconnaissance pilot through the ledger.

Examples:
    python scripts/oc_firecrawl_federation_pilot.py --source powo
    python scripts/oc_firecrawl_federation_pilot.py --source wfo
    python scripts/oc_firecrawl_federation_pilot.py --source all --limit 50

Every source goes through ``app.federation.federation_pilot.run_pilot``: the
acquisition ledger (``migrations/20260930_acquisition_ledger.sql``) must be
present, a completed ledger record is reused, existing corpus/source-registry
holdings are searched first, and the mapper runs only on an acquired ledger
lease. A missing or incompatible ledger schema aborts with zero provider
calls; there is no direct-call fallback and no bypass flag.

Requires the application database (``PGHOST`` or ``DATABASE_URL``). A live call
passes the SAME gate as the literature Firecrawl provider
(``app.literature_extraction.firecrawl_provider.live_gate``):
``FIRECRAWL_ENABLED=true``, ``FIRECRAWL_DRY_RUN=false``,
``FIRECRAWL_KILL_SWITCH`` unset or ``false``, ``PROVIDER_AUTHORIZED=true``,
``NO_API_MODE=false``, ``FIRECRAWL_API_KEY``, positive
``FIRECRAWL_MAX_CALL_COST_USD`` / ``FIRECRAWL_DAILY_BUDGET_USD``, and the
durable daily budget reservation in the research-station record store, which
is reserved before every paid call. Outputs reconnaissance JSON only. It
never mutates OC scientific stores; it writes only acquisition-ledger rows
and budget reservations.

A stored map is reused whenever it covers the requested ``--limit`` and
``--sitemap`` (same sitemap mode, stored limit >= requested). A request it
does not cover makes no paid call unless ``--operator-override OPERATOR`` is
given; the override is logged and still goes through the ledger lease.

Exit status: 0 every source answered (fetched, ledger cache hit, or already
held); 2 aborted before any provider call (no database / ledger schema);
3 at least one source blocked, in flight, not covered, awaiting operator
review, or failed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.federation.federation_pilot import CorpusHoldings, run_pilot
from app.federation.firecrawl_mapper import FirecrawlFederationMapper

SOURCES = {
    "powo": {
        "source_id": "powo_kew",
        "root_url": "https://powo.science.kew.org/",
        "search": "Phragmipedium",
    },
    "wfo": {
        "source_id": "world_flora_online",
        "root_url": "https://www.worldfloraonline.org/",
        "search": "Phragmipedium",
    },
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bounded Firecrawl source-reconnaissance pilot for OC federation."
    )
    parser.add_argument(
        "--source",
        choices=("powo", "wfo", "all"),
        default="all",
        help="Source to map. Default: all.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum URLs requested from Firecrawl per source (1-1000; default 50).",
    )
    parser.add_argument(
        "--sitemap",
        choices=("include", "only", "skip"),
        default="include",
        help="Firecrawl sitemap handling. Default: include.",
    )
    parser.add_argument(
        "--operator-override",
        metavar="OPERATOR",
        help=(
            "Operator identity authorising a paid re-map when the stored result "
            "does not cover --limit/--sitemap. Logged; still ledger-leased."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path. Otherwise prints to stdout.",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 1000:
        # Rejected before any ledger claim, so a bad argument costs no lease.
        parser.error("--limit must be between 1 and 1000")
    return args


def _database_url() -> str | None:
    """The application database, never the SQLite fallback of ``get_database_url``."""
    if not (os.environ.get("PGHOST") or os.environ.get("DATABASE_URL")):
        return None
    from app.database import get_database_url

    return get_database_url()


def _sqlalchemy_url(url: str) -> str:
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def build_holdings_check(database_url: str):
    """Corpus + source-registry holdings lookup on the application database."""

    def connect():
        import psycopg

        url = database_url
        for prefix in ("postgresql+psycopg://", "postgres://"):
            if url.startswith(prefix):
                url = "postgresql://" + url[len(prefix) :]
        return psycopg.connect(url, connect_timeout=10)

    return CorpusHoldings(connect)


def build_spend_authority(database_url: str, env):
    """Production budget authority: the provider's governor and reservation.

    ``None`` (the gate then refuses with DURABLE_BUDGET_AUTHORITY_REQUIRED)
    when the configuration cannot be read.
    """
    from app.federation.federation_pilot import SpendAuthority, load_config
    from app.literature_extraction.firecrawl_provider import (
        AcquisitionBlocked,
        PostgresFirecrawlReservation,
    )

    try:
        config = load_config(env)
    except AcquisitionBlocked:
        return None
    if config.dry_run or config.max_call_cost <= 0 or config.daily_budget <= 0:
        return None
    from app.literature_extraction.firecrawl_runtime import _governor

    def connect():
        import psycopg

        url = database_url
        for prefix in ("postgresql+psycopg://", "postgres://"):
            if url.startswith(prefix):
                url = "postgresql://" + url[len(prefix) :]
        return psycopg.connect(url, connect_timeout=10)

    reservation = PostgresFirecrawlReservation(connect)
    return SpendAuthority(
        governor=_governor(config),
        reserve=reservation,
        reserve_credits=reservation.reserve_credits,
        observe_credits=reservation.observe_credits,
    )


def _emit(result: dict, output: Path | None) -> None:
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
        print(output)
    else:
        print(rendered)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    names = tuple(SOURCES) if args.source == "all" else (args.source,)
    database_url = _database_url()
    if database_url is None:
        _emit(
            {
                "pilot": "firecrawl-federation-phragmipedium-v1",
                "status": "aborted",
                "reason": "LEDGER_DATABASE_REQUIRED",
                "provider_calls": 0,
                "automatic_publication_allowed": False,
            },
            args.output,
        )
        return 2

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(_sqlalchemy_url(database_url), pool_pre_ping=True)
    session = sessionmaker(bind=engine)()
    try:
        report = run_pilot(
            session=session,
            sources={name: SOURCES[name] for name in names},
            mapper=FirecrawlFederationMapper(),
            holdings=build_holdings_check(database_url),
            env=os.environ,
            limit=args.limit,
            sitemap=args.sitemap,
            authority=build_spend_authority(database_url, os.environ),
            operator_override=args.operator_override,
        )
    finally:
        session.close()
        engine.dispose()
    _emit(report.as_dict(), args.output)
    if report.status == "aborted":
        return 2
    return 0 if report.resolved else 3


if __name__ == "__main__":
    raise SystemExit(main())
