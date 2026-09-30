from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.federation.firecrawl_mapper import build_source_profile
from app.federation.shared_firecrawl import SharedFirecrawlFederationService


def _service():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    mapper = Mock()
    mapper.map_source.return_value = build_source_profile(
        source_id="powo",
        root_url="https://powo.science.kew.org/",
        urls=("https://powo.science.kew.org/taxon/test",),
    )
    return SharedFirecrawlFederationService(session, mapper=mapper), mapper


def test_two_modules_trigger_one_firecrawl_call():
    service, mapper = _service()
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
    assert cached is not None\n    assert cached.urls == profile.urls
    mapper.map_source.assert_called_once()
    assert service.ledger.metrics()["credits_spent"] == 1


def test_different_searches_are_distinct_acquisitions():
    service, mapper = _service()
    service.map_source(
        consumer_module="lexicon", source_id="powo",
        root_url="https://powo.science.kew.org/", search="Phragmipedium", limit=25,
    )
    service.map_source(
        consumer_module="lexicon", source_id="powo",
        root_url="https://powo.science.kew.org/", search="Masdevallia", limit=25,
    )
    assert mapper.map_source.call_count == 2


def test_equivalent_root_urls_share_one_firecrawl_call():
    service, mapper = _service()
    service.map_source(
        consumer_module="lexicon", source_id="powo",
        root_url="https://POWO.science.kew.org:443/?utm_source=x#top",
        search="Phragmipedium", limit=25,
    )
    status, cached = service.map_source(
        consumer_module="atlas", source_id="powo",
        root_url="https://powo.science.kew.org/",
        search="Phragmipedium", limit=25,
    )
    assert status == "cache_hit"
    assert cached is not None
    mapper.map_source.assert_called_once()
