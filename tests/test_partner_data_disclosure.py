import pytest

from app.data_governance import (
    DataDisclosureDenied,
    DataPolicyDecision,
    DisclosureMode,
    apply_disclosure,
)


def _decision(
    *,
    allowed=True,
    disclosure=DisclosureMode.FULL,
    location=DisclosureMode.FULL,
    image=DisclosureMode.FULL,
):
    return DataPolicyDecision(
        allowed=allowed,
        disclosure=disclosure,
        location_disclosure=location,
        image_disclosure=image,
        reason_codes=("TEST",),
        policy_id="policy-1",
        authority_org="partner",
        attribution_required=True,
    )


def test_denied_payload_raises_without_returning_data():
    with pytest.raises(DataDisclosureDenied):
        apply_disclosure(
            _decision(allowed=False, disclosure=DisclosureMode.DENY),
            {"scientific_name": "Example orchid", "latitude": 35.1},
        )


def test_generalized_location_removes_exact_site_fields_but_keeps_region():
    result = apply_disclosure(
        _decision(location=DisclosureMode.GENERALIZED),
        {
            "scientific_name": "Example orchid",
            "latitude": 35.1,
            "longitude": -120.4,
            "site_name": "Private conservation site",
            "landowner": "Private landowner",
            "country": "US",
            "state_province": "California",
        },
    )
    assert "latitude" not in result
    assert "longitude" not in result
    assert "site_name" not in result
    assert "landowner" not in result
    assert result["country"] == "US"
    assert result["state_province"] == "California"
    assert result["location_disclosure"] == "GENERALIZED"


def test_image_denial_is_independent_from_scientific_record_access():
    result = apply_disclosure(
        _decision(image=DisclosureMode.DENY),
        {
            "scientific_name": "Example orchid",
            "pollinator": "Example pollinator",
            "image_url": "https://example.invalid/restricted.jpg",
            "thumbnail_url": "https://example.invalid/restricted-thumb.jpg",
        },
    )
    assert result["scientific_name"] == "Example orchid"
    assert result["pollinator"] == "Example pollinator"
    assert "image_url" not in result
    assert "thumbnail_url" not in result


def test_existence_only_preserves_safe_provenance_not_sensitive_payload():
    result = apply_disclosure(
        _decision(
            disclosure=DisclosureMode.EXISTENCE_ONLY,
            location=DisclosureMode.DENY,
            image=DisclosureMode.DENY,
        ),
        {
            "record_id": "obs-1",
            "scientific_name": "Example orchid",
            "doi": "10.0000/example",
            "latitude": 35.1,
            "longitude": -120.4,
            "site_name": "Private site",
            "image_url": "https://example.invalid/restricted.jpg",
        },
    )
    assert result["exists"] is True
    assert result["provenance"]["record_id"] == "obs-1"
    assert result["provenance"]["doi"] == "10.0000/example"
    assert "latitude" not in result["provenance"]
    assert "image_url" not in result["provenance"]


def test_aggregate_only_never_returns_raw_record():
    result = apply_disclosure(
        _decision(
            disclosure=DisclosureMode.AGGREGATE_ONLY,
            location=DisclosureMode.EXISTENCE_ONLY,
            image=DisclosureMode.DENY,
        ),
        {
            "record_id": "obs-2",
            "scientific_name": "Example orchid",
            "pollinator": "Sensitive observation detail",
            "latitude": 35.1,
        },
    )
    assert result["raw_record_disclosed"] is False
    assert result["aggregate_required"] is True
    assert "pollinator" not in result
    assert "latitude" not in result
    assert result["provenance"]["record_id"] == "obs-2"


def test_output_carries_policy_and_authority_metadata():
    result = apply_disclosure(
        _decision(location=DisclosureMode.GENERALIZED, image=DisclosureMode.DENY),
        {"scientific_name": "Example orchid", "country": "US"},
    )
    governance = result["_governance"]
    assert governance["policy_id"] == "policy-1"
    assert governance["authority_org"] == "partner"
    assert governance["attribution_required"] is True
