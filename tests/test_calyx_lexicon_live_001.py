from __future__ import annotations

from app.lexicon import routes


def test_slug_lookup_matches_preferred_term(monkeypatch):
    monkeypatch.setattr(
        routes,
        "_load_entries",
        lambda **_: [
            {
                "slug": "velamen",
                "preferred_term": "Velamen",
                "synonyms": ["velamen radicum"],
                "id": "concept-1",
            }
        ],
    )

    entry = routes._load_entry_by_slug("Velamen")

    assert entry is not None
    assert entry["id"] == "concept-1"


def test_slug_lookup_matches_reviewed_synonym(monkeypatch):
    monkeypatch.setattr(
        routes,
        "_load_entries",
        lambda **_: [
            {
                "slug": "labellum",
                "preferred_term": "Labellum",
                "synonyms": ["lip"],
                "id": "concept-2",
            }
        ],
    )

    entry = routes._load_entry_by_slug("lip")

    assert entry is not None
    assert entry["slug"] == "labellum"


def test_direct_slug_route_is_canonical_and_nonpublishing(monkeypatch):
    monkeypatch.setattr(
        routes,
        "_load_entry_by_slug",
        lambda slug: {
            "id": "concept-3",
            "slug": slug,
            "preferred_term": "Velamen",
            "source_system": "oc_concepts",
        },
    )

    payload = routes.get_approved_entry_by_slug("velamen")

    assert payload["entry"]["source_system"] == "oc_concepts"
    assert payload["source_of_truth"] == "oc_concepts"
    assert payload["automatic_publication"] is False
    assert payload["visibility"] == "ACTIVE + APPROVED concepts only"


def test_capabilities_advertise_live_entry_and_definition_search():
    payload = routes.lexicon_capabilities()

    assert payload["direct_entry_lookup"] == "/api/lexicon/entries/{slug}"
    assert payload["search_scope"] == ["approved labels", "approved definitions"]
    assert payload["governance"]["invented_enrichment_prohibited"] is True
