"""Focused tests for budget-guarded Firecrawl morphology evidence (AC-3)."""

import pytest

from app.federation.morphology_evidence import (
    InMemoryAcquisitionLedger,
    MorphologyEvidenceService,
    SourcePolicy,
    extract_morphological_statements,
    plan_evidence_acquisition,
)

POLICIES = {
    "powo": SourcePolicy(
        source_id="powo",
        root_url="https://powo.science.kew.org/",
        terms_reviewed=True,
        robots_compliant=True,
        attribution="Plants of the World Online, Royal Botanic Gardens, Kew",
    ),
    "unreviewed-blog": SourcePolicy(
        source_id="unreviewed-blog",
        root_url="https://example-blog.invalid/",
        terms_reviewed=False,
        robots_compliant=True,
        attribution="Example blog",
    ),
}

PAGE_TEXT = (
    "The petal color of Phragmipedium besseae is bright red. "
    "The pouch shape is slipper-shaped and glossy. "
    "Leaf length reaches 20 to 35 cm. "
    "It was first described in 1981."
)


def _service(extractor=None, max_credits=5):
    calls = []

    def _default_extractor(*, url, taxon_name):
        calls.append(url)
        return PAGE_TEXT

    service = MorphologyEvidenceService(
        InMemoryAcquisitionLedger(),
        extractor=extractor or _default_extractor,
        policies=POLICIES,
        max_credits=max_credits,
    )
    return service, calls


def test_unpermitted_source_fails_closed_without_call():
    service, calls = _service()
    result = service.extract_morphology(
        consumer_module="matrix",
        source_id="unreviewed-blog",
        url="https://example-blog.invalid/phrag",
        taxon_name="Phragmipedium besseae",
        characters=["petal_color"],
    )
    assert result["status"] == "source_not_permitted"
    assert calls == []
    unknown = service.extract_morphology(
        consumer_module="matrix",
        source_id="never-heard-of-it",
        url="https://mystery.invalid/x",
        taxon_name="Phragmipedium besseae",
        characters=["petal_color"],
    )
    assert unknown["status"] == "source_not_permitted"
    assert calls == []


def test_budget_exhaustion_blocks_provider_call():
    service, calls = _service(max_credits=1)
    first = service.extract_morphology(
        consumer_module="matrix",
        source_id="powo",
        url="https://powo.science.kew.org/taxon/1",
        taxon_name="Phragmipedium besseae",
        characters=["petal_color"],
    )
    assert first["status"] == "fetched"
    assert len(calls) == 1
    second = service.extract_morphology(
        consumer_module="matrix",
        source_id="powo",
        url="https://powo.science.kew.org/taxon/2",
        taxon_name="Phragmipedium kovachii",
        characters=["petal_color"],
    )
    assert second["status"] == "budget_exhausted"
    assert len(calls) == 1
    assert service.ledger.metrics()["credits_spent"] == 1


def test_identical_request_is_cache_hit_with_zero_additional_credits():
    service, calls = _service()
    kwargs = dict(
        consumer_module="matrix",
        source_id="powo",
        url="https://powo.science.kew.org/taxon/1?utm_source=newsletter",
        taxon_name="Phragmipedium besseae",
        characters=["petal_color", "pouch_shape"],
    )
    first = service.extract_morphology(**kwargs)
    second = service.extract_morphology(**{**kwargs, "url": "https://powo.science.kew.org/taxon/1"})
    assert first["status"] == "fetched"
    assert second["status"] == "cache_hit"
    assert len(calls) == 1
    assert service.ledger.metrics()["credits_spent"] == 1
    assert second["items"] == first["items"]


def test_extracted_statements_are_bounded_verbatim_excerpts_with_attribution():
    service, _ = _service()
    result = service.extract_morphology(
        consumer_module="matrix",
        source_id="powo",
        url="https://powo.science.kew.org/taxon/1",
        taxon_name="Phragmipedium besseae",
        characters=["petal_color", "pouch_shape", "leaf_length_cm", "spur_length_mm"],
    )
    assert result["status"] == "fetched"
    by_character = {item["character"]: item for item in result["items"]}
    assert by_character["petal_color"]["excerpt"] == "The petal color of Phragmipedium besseae is bright red."
    assert by_character["leaf_length_cm"]["excerpt"] == "Leaf length reaches 20 to 35 cm."
    assert "spur_length_mm" not in by_character
    for item in result["items"]:
        assert len(item["excerpt"]) <= 280
        assert item["evidence_class"] == "literature_excerpt_unverified"
        assert item["review_state"] == "review_required"
        assert item["source_url"] == "https://powo.science.kew.org/taxon/1"
        assert "Kew" in item["attribution"]
    # no image or full-text cloning: payload holds bounded excerpts only
    cached = service.ledger.cached_payload(next(iter(service.ledger.keys())))
    assert PAGE_TEXT not in cached


def test_extractor_failure_marks_ledger_failed_and_raises():
    def _boom(*, url, taxon_name):
        raise RuntimeError("provider 500")

    service, _ = _service(extractor=_boom)
    with pytest.raises(RuntimeError, match="provider 500"):
        service.extract_morphology(
            consumer_module="matrix",
            source_id="powo",
            url="https://powo.science.kew.org/taxon/9",
            taxon_name="Phragmipedium besseae",
            characters=["petal_color"],
        )
    assert service.ledger.metrics()["failures"] == 1
    assert service.ledger.metrics()["credits_spent"] == 0


def test_plan_evidence_acquisition_skips_characters_with_existing_coverage():
    plan = plan_evidence_acquisition(
        ["petal_color", "pouch_shape", "leaf_length_cm"],
        existing_coverage={
            "petal_color": [{"source_ref": "kg:traits:1234"}],
            "pouch_shape": [],
        },
    )
    assert plan["skip_provider_call"] == ["petal_color"]
    assert plan["needs_acquisition"] == ["pouch_shape", "leaf_length_cm"]


def test_sentence_extraction_is_case_insensitive_and_bounded():
    text = "PETAL COLOR: deep rose. " + ("Padding sentence. " * 40) + "The spur is long."
    items = extract_morphological_statements(text, ["petal_color"], excerpt_limit=60)
    assert len(items) == 1
    assert len(items[0]["excerpt"]) <= 60
    assert items[0]["excerpt_truncated"] is False
