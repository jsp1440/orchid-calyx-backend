from app.intake.extractor import content_hash, extract


def test_extracts_species_deadline_organization_and_tasks():
    text = (
        "A newly described orchid species Pleurothallis pembertoniii was reported by "
        "Kew Gardens. The Darwin Initiative grant deadline is July 20, 2026."
    )
    result = extract(text)
    names = {(e.entity_type, e.canonical_name) for e in result.entities}
    assert ("species", "Pleurothallis pembertoniii") in names
    assert ("deadline", "July 20, 2026") in names
    assert ("organization", "Kew Gardens") in names
    assert ("organization", "Darwin Initiative") in names
    assert ("species", "Initiative grant") not in names
    assert any(t.task_type == "verify_taxonomy" for t in result.tasks)
    assert any(t.task_type == "review_funding" for t in result.tasks)


def test_extract_is_deterministic_and_hash_is_idempotent():
    text = "Orchid species Lepanthes leonmoralesii was formally described."
    first = extract(text).model_dump()
    second = extract(text).model_dump()
    assert first == second
    assert content_hash(text) == content_hash(text)


def test_api_and_doi_are_retained_as_provenance_entities():
    text = "API documentation: https://example.org/api and DOI 10.1111/gcb.12345"
    result = extract(text)
    assert any(e.entity_type == "api_or_url" for e in result.entities)
    assert any(e.metadata.get("scheme") == "doi" for e in result.entities)
    assert any(t.task_type == "review_api" for t in result.tasks)
