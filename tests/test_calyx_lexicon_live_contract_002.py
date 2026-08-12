from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.lexicon import routes


def test_slug_lookup_requires_exact_canonical_slug_or_label(monkeypatch):
    monkeypatch.setattr(
        routes,
        "_load_entries",
        lambda **_kwargs: [
            {
                "slug": "velamen-radicum",
                "preferred_term": "Velamen radicum",
                "synonyms": ["root velamen"],
            },
            {
                "slug": "velamen",
                "preferred_term": "Velamen",
                "synonyms": [],
            },
        ],
    )

    entry = routes._load_entry_by_slug("Velamen")
    assert entry is not None
    assert entry["slug"] == "velamen"


def test_slug_lookup_tries_hyphenated_and_space_normalized_forms(monkeypatch):
    queries: list[str] = []

    def fake_load_entries(*, q: str, limit: int):
        queries.append(q)
        if q == "labellum lip":
            return [
                {
                    "id": "concept-lip",
                    "concept_id": "concept-lip",
                    "slug": "labellum-lip",
                    "preferred_term": "Labellum / Lip",
                    "synonyms": [],
                }
            ]
        return []

    monkeypatch.setattr(routes, "_load_entries", fake_load_entries)

    entry = routes._load_entry_by_slug("labellum-lip")

    assert entry is not None
    assert entry["slug"] == "labellum-lip"
    assert queries == ["labellum-lip", "labellum lip"]


def test_slug_lookup_does_not_return_definition_only_near_match(monkeypatch):
    monkeypatch.setattr(
        routes,
        "_load_entries",
        lambda **_kwargs: [
            {
                "slug": "orchid-root",
                "preferred_term": "Orchid root",
                "synonyms": [],
            }
        ],
    )

    assert routes._load_entry_by_slug("velamen") is None


def test_public_slug_endpoint_fails_closed_when_no_approved_entry(monkeypatch):
    monkeypatch.setattr(routes, "_load_entry_by_slug", lambda _slug: None)

    with pytest.raises(HTTPException) as exc_info:
        routes.get_approved_entry_by_slug("velamen")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "LEXICON_APPROVED_ENTRY_NOT_FOUND"


def test_public_slug_endpoint_preserves_canonical_authority(monkeypatch):
    canonical = {
        "id": "concept-1",
        "concept_id": "concept-1",
        "slug": "velamen",
        "preferred_term": "Velamen",
        "quick_definition": "Reviewed canonical definition",
        "source_system": "oc_concepts",
    }
    monkeypatch.setattr(routes, "_load_entry_by_slug", lambda _slug: canonical)

    payload = routes.get_approved_entry_by_slug("velamen")

    assert payload["entry"] is canonical
    assert payload["source_of_truth"] == "oc_concepts"
    assert payload["automatic_publication"] is False
