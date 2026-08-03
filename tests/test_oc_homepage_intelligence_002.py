from app.parallel_platform.homepage_intelligence import (
    HomepageSection,
    build_homepage_document,
)


def test_homepage_fills_missing_sections_with_unavailable_not_empty_data():
    document = build_homepage_document(
        (
            HomepageSection(
                section_id="mission",
                availability="available",
                data={"heading": "Connect orchid knowledge across evidence and people."},
                evidence=("policy:mission",),
                provenance=("orchid-continuum",),
            ),
        )
    )
    mission = next(section for section in document["sections"] if section["id"] == "mission")
    genus = next(section for section in document["sections"] if section["id"] == "featured_genus")
    assert mission["availability"] == "available"
    assert genus["availability"] == "unavailable"
    assert genus["data"] is None


def test_available_section_requires_data():
    try:
        HomepageSection(section_id="research", availability="available", data=None)
    except ValueError as exc:
        assert str(exc) == "AVAILABLE_SECTION_REQUIRES_DATA"
    else:
        raise AssertionError("available empty section was accepted")


def test_homepage_governance_disallows_browser_scoring():
    document = build_homepage_document(())
    assert document["governance"]["client_scoring_allowed"] is False
    assert document["governance"]["attribution_required"] is True
