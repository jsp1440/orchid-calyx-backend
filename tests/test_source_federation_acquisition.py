from app.source_federation.acquisition import (
    AcquisitionRecord,
    AcquisitionRequest,
    canonicalize_url,
    resource_key,
)


def test_canonicalize_url_removes_tracking_and_fragment():
    assert canonicalize_url(
        "HTTPS://Example.COM/species?id=7&utm_source=x&fbclid=y#section"
    ) == "https://example.com/species?id=7"


def test_canonicalize_url_sorts_meaningful_query():
    assert canonicalize_url(
        "https://example.com/search?b=2&a=1"
    ) == "https://example.com/search?a=1&b=2"


def test_equivalent_urls_share_resource_key():
    left = resource_key(
        url="https://example.com/taxon?id=1&utm_campaign=x",
        provider="POWO",
    )
    right = resource_key(
        url="https://EXAMPLE.com/taxon?id=1#ignored",
        provider="powo",
    )
    assert left == right


def test_stable_provider_identifier_wins_over_url_shape():
    left = resource_key(
        url="https://example.com/old-route",
        provider="wfo",
        stable_identifier="wfo-0000123456",
    )
    right = resource_key(
        url="https://example.com/new-route",
        provider="WFO",
        stable_identifier="wfo-0000123456",
    )
    assert left == right


def test_completed_record_is_provenance_bearing():
    request = AcquisitionRequest(
        url="https://example.com/species/1",
        provider="test",
        consumer_module="lexicon",
    )
    record = AcquisitionRecord.completed(
        request=request,
        content=b"orchid evidence",
        provenance={"source": "fixture"},
        credits_spent=1,
    )
    assert record.key == request.key
    assert record.consumers == ("lexicon",)
    assert record.credits_spent == 1
    assert record.provenance["source"] == "fixture"


def test_default_ports_deduplicate():
    assert canonicalize_url("https://example.com:443/data") == canonicalize_url("https://example.com/data")
    assert canonicalize_url("http://example.com:80/data") == canonicalize_url("http://example.com/data")


def test_whitespace_identifier_falls_back_to_url():
    assert resource_key(url="https://example.com/a", provider="powo", stable_identifier="   ") != resource_key(url="https://example.com/b", provider="powo", stable_identifier="   ")


def test_completed_record_requires_provenance():
    import pytest
    request = AcquisitionRequest(url="https://example.com/a", provider="test", consumer_module="matrix")
    with pytest.raises(ValueError, match="provenance"):
        AcquisitionRecord.completed(request=request, content=b"x", provenance={})


def test_completed_provenance_is_immutable():
    import pytest
    request = AcquisitionRequest(url="https://example.com/a", provider="test", consumer_module="matrix")
    record = AcquisitionRecord.completed(request=request, content=b"x", provenance={"source": "fixture"})
    with pytest.raises(TypeError):
        record.provenance["source"] = "rewritten"
