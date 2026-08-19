from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import HTTPException

from app.lexicon import routes


def test_slug_normalization_handles_hyphenated_and_punctuated_labels():
    assert routes._slug("semi-terete") == "semi-terete"
    assert routes._slug("Labellum / Lip") == "labellum-lip"
    assert routes._slug("  CAM photosynthesis  ") == "cam-photosynthesis"


def test_slug_lookup_uses_exact_approved_concept_identity(monkeypatch):
    concept_id = UUID("11111111-1111-1111-1111-111111111111")
    canonical = {
        "id": str(concept_id),
        "concept_id": str(concept_id),
        "slug": "labellum-lip",
        "preferred_term": "Labellum / Lip",
        "source_system": "oc_concepts",
    }
    seen: list[str] = []

    monkeypatch.setattr(
        routes,
        "_find_approved_concept_id_by_slug",
        lambda slug: seen.append(slug) or concept_id,
    )
    monkeypatch.setattr(
        routes,
        "_load_entry_by_concept_id",
        lambda value: canonical if value == concept_id else None,
    )

    entry = routes._load_entry_by_slug("labellum-lip")

    assert seen == ["labellum-lip"]
    assert entry is canonical


def test_slug_lookup_returns_none_without_approved_exact_label(monkeypatch):
    monkeypatch.setattr(routes, "_find_approved_concept_id_by_slug", lambda _slug: None)
    assert routes._load_entry_by_slug("velamen") is None


def test_ambiguous_approved_slug_fails_closed(monkeypatch):
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, _query, _params):
            return None

        def fetchall(self):
            return [
                {"concept_id": UUID("11111111-1111-1111-1111-111111111111")},
                {"concept_id": UUID("22222222-2222-2222-2222-222222222222")},
            ]

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(routes, "_connect", lambda: Connection())

    with pytest.raises(HTTPException) as exc_info:
        routes._find_approved_concept_id_by_slug("lip")

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "LEXICON_APPROVED_SLUG_AMBIGUOUS"
    assert exc_info.value.detail["slug"] == "lip"


def test_public_slug_endpoint_fails_closed_when_no_approved_entry(monkeypatch):
    monkeypatch.setattr(routes, "_load_entry_by_slug", lambda _slug: None)

    with pytest.raises(HTTPException) as exc_info:
        routes.get_approved_entry_by_slug("velamen")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "LEXICON_APPROVED_ENTRY_NOT_FOUND"


def test_public_slug_endpoint_preserves_canonical_authority_and_release(monkeypatch):
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

    assert payload["release"] == "CALYX-LEXICON-LIVE-002"
    assert payload["entry"] is canonical
    assert payload["source_of_truth"] == "oc_concepts"
    assert payload["automatic_publication"] is False


def test_search_query_uses_only_approved_labels_and_definitions():
    # Static contract guard against accidentally widening public search to pending prose.
    import inspect

    source = inspect.getsource(routes._load_entries)
    assert "sx.review_state='APPROVED'" in source
    assert "sd.review_state='APPROVED'" in source
