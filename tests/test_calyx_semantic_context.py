from __future__ import annotations

from uuid import UUID

from app.calyx_conversation import continuum_context, semantic_context


class _FakeCursor:
    def __init__(self) -> None:
        self._rows = []
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params):
        self.calls += 1
        concept_id = UUID("12345678-1234-5678-1234-567812345678")
        if self.calls == 1:
            assert "velamen" in params[0]
            self._rows = [
                {
                    "concept_id": concept_id,
                    "concept_uri": "https://orchidcontinuum.org/concepts/velamen",
                    "label": "velamen",
                    "normalized_label": "velamen",
                    "label_type": "PREFERRED",
                }
            ]
        else:
            assert concept_id in params[0]
            self._rows = [
                {
                    "concept_id": concept_id,
                    "definition_type": "GLOSSARY",
                    "text": "A multilayered root covering found in many epiphytic orchids.",
                }
            ]

    def fetchall(self):
        return list(self._rows)


class _FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = _FakeCursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_instance


def test_candidate_phrases_prefers_bounded_longer_phrases():
    phrases = semantic_context.candidate_phrases(
        "How does velamen help epiphytic orchids conserve water?"
    )
    assert "velamen" in phrases
    assert "epiphytic orchids" in phrases
    assert len(phrases) <= 96


def test_build_semantic_context_returns_approved_glossary_doorway(monkeypatch):
    monkeypatch.setattr(semantic_context, "_connect", lambda: _FakeConnection())

    result = semantic_context.build_semantic_context(
        "What does velamen do in epiphytic orchids?"
    )

    assert result["status"] == "available"
    assert result["read_only"] is True
    assert result["automatic_publication"] is False
    assert result["links"] == [
        {
            "concept_id": "12345678-1234-5678-1234-567812345678",
            "concept_uri": "https://orchidcontinuum.org/concepts/velamen",
            "term": "velamen",
            "matched_normalized_label": "velamen",
            "definition": "A multilayered root covering found in many epiphytic orchids.",
            "href": "/api/lexicon/concepts/12345678-1234-5678-1234-567812345678",
            "source_of_truth": "oc_concepts",
            "review_state": "approved",
        }
    ]


def test_continuum_context_carries_semantic_links_without_requiring_a_taxon(monkeypatch):
    semantic = {
        "status": "available",
        "links": [
            {
                "concept_id": "concept-velamen",
                "term": "velamen",
                "definition": "root covering",
                "href": "/api/lexicon/concepts/concept-velamen",
            }
        ],
        "source_of_truth": "oc_concepts",
        "read_only": True,
        "automatic_publication": False,
    }
    monkeypatch.setattr(continuum_context, "build_semantic_context", lambda message: semantic)

    result = continuum_context.build_continuum_context(
        "How does velamen function in epiphytic orchids?"
    )

    assert result["resolved_genera"] == []
    assert result["semantic_context"] == semantic
    assert result["semantic_links"] == semantic["links"]
    assert result["read_only"] is True
    assert result["knowledge_graph_mutation"] is False
