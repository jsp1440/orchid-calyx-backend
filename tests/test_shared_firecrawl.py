from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.federation.firecrawl_mapper import build_source_profile
from app.federation.shared_firecrawl import SharedFirecrawlFederationService
from app.source_federation.acquisition_models import AcquisitionLedgerRow
from tests.acquisition_ledger_backends import (
    LEDGER_BACKENDS,
    ledger_engine_fixture,  # noqa: F401 - the ``ledger_engine`` fixture
)


def _service(engine=None):
    if engine is None:
        engine = create_engine("sqlite:///:memory:")
        # Only the ledger table: the shared Base also carries schema-qualified
        # tables (e.g. research_station.*) that SQLite cannot create, so a
        # full-suite run that has imported those models fails here otherwise.
        Base.metadata.create_all(engine, tables=[AcquisitionLedgerRow.__table__])
    session = sessionmaker(bind=engine)()
    mapper = Mock()
    mapper.map_source.return_value = build_source_profile(
        source_id="powo",
        root_url="https://powo.science.kew.org/",
        urls=("https://powo.science.kew.org/taxon/test",),
    )
    return SharedFirecrawlFederationService(session, mapper=mapper), mapper


@LEDGER_BACKENDS
def test_two_modules_trigger_one_firecrawl_call(ledger_engine):
    service, mapper = _service(ledger_engine)
    first, profile = service.map_source(
        consumer_module="lexicon",
        source_id="powo",
        root_url="https://powo.science.kew.org/",
        search="Phragmipedium",
        limit=25,
    )
    second, cached = service.map_source(
        consumer_module="matrix",
        source_id="powo",
        root_url="https://powo.science.kew.org/",
        search="Phragmipedium",
        limit=25,
    )
    assert first == "fetched"
    assert profile is not None
    assert second == "cache_hit"
    assert cached is not None
    assert cached.urls == profile.urls
    mapper.map_source.assert_called_once()
    assert service.ledger.metrics()["credits_spent"] == 1


@LEDGER_BACKENDS
def test_different_searches_are_distinct_acquisitions(ledger_engine):
    service, mapper = _service(ledger_engine)
    service.map_source(
        consumer_module="lexicon",
        source_id="powo",
        root_url="https://powo.science.kew.org/",
        search="Phragmipedium",
        limit=25,
    )
    service.map_source(
        consumer_module="lexicon",
        source_id="powo",
        root_url="https://powo.science.kew.org/",
        search="Masdevallia",
        limit=25,
    )
    assert mapper.map_source.call_count == 2


@LEDGER_BACKENDS
def test_equivalent_root_urls_share_one_firecrawl_call(ledger_engine):
    service, mapper = _service(ledger_engine)
    service.map_source(
        consumer_module="lexicon",
        source_id="powo",
        root_url="https://POWO.science.kew.org:443/?utm_source=x#top",
        search="Phragmipedium",
        limit=25,
    )
    status, cached = service.map_source(
        consumer_module="atlas",
        source_id="powo",
        root_url="https://powo.science.kew.org/",
        search="Phragmipedium",
        limit=25,
    )
    assert status == "cache_hit"
    assert cached is not None
    mapper.map_source.assert_called_once()
