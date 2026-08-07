from app.species_exhibit.service import (
    CONTRACT,
    _build_card,
    _confidence,
    _evidence_receipt,
    _graph_fact,
    _representative_media,
    _split_scientific_name,
    _state,
)


def test_contract_is_stable():
    assert CONTRACT == "calyx-species-exhibit-v1"


def test_unavailable_is_not_zero():
    result = _state(None, limitation="not connected")
    assert result["state"] == "unavailable"
    assert result["value"] is None
    assert result["limitation"] == "not connected"


def test_available_empty_is_not_fabricated():
    result = _state([])
    assert result["state"] == "unavailable"


def test_available_evidence_is_preserved():
    payload = {"taxon_id": "42", "scientific_name": "Cattleya labiata"}
    result = _state(payload)
    assert result["state"] == "available"
    assert result["value"] == payload


def test_scientific_name_separates_binomial_and_authorship():
    display_name, authorship = _split_scientific_name("Cattleya labiata Lindl.")
    assert display_name == "Cattleya labiata"
    assert authorship == "Lindl."


def test_representative_media_rejects_duplicate_url_across_cards():
    media = [
        {"id": 1, "image_url": "https://example.test/a.jpg", "image_source": "GBIF"},
        {"id": 2, "image_url": "https://example.test/b.jpg", "image_source": "iNaturalist"},
    ]
    used = {"https://example.test/a.jpg"}
    selected = _representative_media(media, used)
    assert selected is not None
    assert selected["url"] == "https://example.test/b.jpg"
    assert selected["identification_state"] == "source_record_not_independently_verified"


def test_graph_caption_is_species_specific_and_source_bound():
    graph = [
        {
            "edge_type": "pollinated_by",
            "display_label": "Euglossa example",
            "source_table": "pollinator_observations",
            "source_pk": "77",
            "evidence_class": "direct",
            "confidence_score": 0.81,
            "confidence_label": "moderate",
        }
    ]
    caption, fact, provenance = _graph_fact("Cattleya labiata", graph)
    assert caption == "Cattleya labiata: pollinated by — Euglossa example."
    assert fact == "Cattleya labiata — pollinated by: Euglossa example"
    assert provenance is not None
    assert provenance["source_table"] == "pollinator_observations"


def test_graph_caption_is_unavailable_without_persisted_relation():
    caption, fact, provenance = _graph_fact("Cattleya labiata", [])
    assert caption is None
    assert fact is None
    assert provenance is None


def test_confidence_uses_only_explicit_persisted_scores():
    unavailable = _confidence([{"confidence_score": None}])
    assert unavailable["state"] == "unavailable"
    assert unavailable["score"] is None

    available = _confidence(
        [
            {"confidence_score": 0.42, "confidence_label": "low"},
            {"confidence_score": 0.88, "confidence_label": "high"},
        ]
    )
    assert available["state"] == "available"
    assert available["score"] == 0.88
    assert available["label"] == "high"


def test_evidence_receipt_is_deterministic_and_content_free():
    media = {"url": "https://example.test/a.jpg"}
    graph = [{"source_table": "kg", "source_pk": "1", "edge_type": "occurs_in"}]
    first = _evidence_receipt("42", media, graph)
    second = _evidence_receipt("42", media, graph)
    assert first == second
    assert len(first["digest"]) == 64
    assert first["contents_included"] is False


def test_card_preserves_unavailable_domains_instead_of_inventing_caption():
    taxon = {
        "id": 42,
        "scientific_name": "Cattleya labiata Lindl.",
        "genus": "Cattleya",
        "image_count": 0,
    }
    card = _build_card(taxon, [], [], set())
    assert card["display_name"] == "Cattleya labiata"
    assert card["authorship"] == "Lindl."
    assert card["caption"] is None
    assert card["distinguishing_fact"] is None
    assert card["evidence_state"] == "provisional"
    assert "media" in card["unavailable_domains"]
    assert "knowledge_graph" in card["unavailable_domains"]
    assert card["publication_authority"] if "publication_authority" in card else True


def test_card_is_available_when_unique_media_and_graph_fact_are_present():
    taxon = {
        "id": 7,
        "scientific_name": "Laelia anceps Lindl.",
        "genus": "Laelia",
        "image_count": 1,
    }
    media = [
        {
            "id": 11,
            "image_url": "https://example.test/laelia.jpg",
            "image_source": "GBIF",
            "image_license": "CC-BY",
            "image_rights_holder": "Example",
            "observer_name": "Observer",
            "gbif_occurrence_key": "123",
        }
    ]
    graph = [
        {
            "edge_type": "occurs_in",
            "display_label": "Mexico",
            "source_table": "occurrences",
            "source_pk": "123",
            "evidence_class": "direct",
            "confidence_score": 0.9,
            "confidence_label": "high",
        }
    ]
    card = _build_card(taxon, media, graph, set())
    assert card["evidence_state"] == "available"
    assert card["representative_media"]["url"] == "https://example.test/laelia.jpg"
    assert card["caption"].startswith("Laelia anceps:")
    assert card["distinguishing_fact"].startswith("Laelia anceps —")
    assert card["confidence"]["score"] == 0.9
    assert card["evidence_receipt"]["contents_included"] is False
