from datetime import UTC, datetime

from app.parallel_platform.homepage_selection import (
    HomepageFeatureCandidate,
    HomepageImageCandidate,
    select_homepage_feature,
)


def test_unlicensed_or_document_images_are_rejected():
    candidate = HomepageFeatureCandidate(
        taxon_id="taxon:1",
        accepted_name="Example orchid",
        content_score=0.9,
        freshness_at=datetime.now(UTC),
        provenance=("taxonomy:release",),
        images=(
            HomepageImageCandidate(
                image_id="image:1",
                url="https://example.invalid/1.jpg",
                license=None,
                attribution=None,
                approved_source=True,
                is_herbarium_or_document_plate=True,
            ),
        ),
    )
    result = select_homepage_feature((candidate,))
    assert result["availability"] == "unavailable"
    assert result["data"] is None


def test_best_eligible_feature_is_selected_server_side():
    image = HomepageImageCandidate(
        image_id="image:2",
        url="https://example.invalid/2.jpg",
        license="CC BY 4.0",
        attribution="Example photographer",
        approved_source=True,
    )
    lower = HomepageFeatureCandidate(
        taxon_id="taxon:a",
        accepted_name="Alpha",
        content_score=0.7,
        freshness_at=datetime(2026, 8, 1, tzinfo=UTC),
        provenance=("source:a",),
        images=(image,),
    )
    higher = HomepageFeatureCandidate(
        taxon_id="taxon:b",
        accepted_name="Beta",
        content_score=0.9,
        freshness_at=datetime(2026, 8, 2, tzinfo=UTC),
        provenance=("source:b",),
        images=(image,),
    )
    result = select_homepage_feature((lower, higher))
    assert result["data"]["taxon_id"] == "taxon:b"
    assert result["client_scoring_allowed"] is False
