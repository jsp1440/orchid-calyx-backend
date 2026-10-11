from app.federation.firecrawl_mapper import build_source_profile


def test_source_profile_prefers_machine_readable_route_when_discovered():
    profile = build_source_profile(
        source_id="powo",
        root_url="https://powo.science.kew.org/",
        urls=[
            "https://powo.science.kew.org/",
            "https://powo.science.kew.org/api/2/search",
            "https://powo.science.kew.org/terms",
            "https://powo.science.kew.org/taxon/example",
        ],
    )

    assert profile.source_id == "powo"
    assert profile.provenance["scientific_status"] == "reconnaissance_only"
    assert profile.provenance["automatic_publication_allowed"] is False
    assert "https://powo.science.kew.org/api/2/search" in profile.api_download_hints
    assert "prefer sanctioned API/download/DwC-A" in profile.preferred_ingestion


def test_source_profile_does_not_invent_machine_readable_route():
    profile = build_source_profile(
        source_id="example",
        root_url="https://example.org/",
        urls=["https://example.org/orchids/phragmipedium"],
    )

    assert profile.api_download_hints == ()
    assert profile.preferred_ingestion.startswith("reconnaissance_only")


def test_source_profile_strips_wfo_jsessionid_before_dedupe():
    profile = build_source_profile(
        source_id="wfo",
        root_url="https://www.worldfloraonline.org/",
        urls=[
            "https://www.worldfloraonline.org/taxon/wfo-0000269982;jsessionid=ABC",
            "https://www.worldfloraonline.org/taxon/wfo-0000269982;jsessionid=XYZ",
        ],
    )

    assert profile.urls == (
        "https://www.worldfloraonline.org/taxon/wfo-0000269982",
    )
    assert profile.candidate_identifiers["wfo_id"] == ("wfo-0000269982",)
