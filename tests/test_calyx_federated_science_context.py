from __future__ import annotations

from app.calyx_conversation import climate_context, external_literature
from app.calyx_conversation.provider import DeterministicGovernedReplyProvider


class _Response:
    def __init__(self, *, json_payload=None, text=""):
        self._json_payload = json_payload
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        return self._json_payload


def test_external_literature_fallback_when_local_index_empty(monkeypatch):
    payload = {
        "resultList": {
            "result": [
                {
                    "title": "Temperature and flowering in Dendrobium",
                    "abstractText": "Cool conditions altered flowering response.",
                    "authorString": "Example A; Example B",
                    "journalTitle": "Orchid Science",
                    "firstPublicationDate": "2024-01-01",
                    "doi": "10.1000/example",
                    "pmid": "12345",
                }
            ]
        }
    }

    monkeypatch.setattr(
        external_literature.requests,
        "get",
        lambda *args, **kwargs: _Response(json_payload=payload),
    )
    result = external_literature.augment_retrieval_with_external_literature(
        {
            "results": [],
            "total_eligible_results": 0,
            "retrieval_mode": "HYBRID",
            "status": "available",
        },
        "Dendrobium winter rest flowering",
        limit=5,
    )

    assert result["status"] == "local_empty_external_literature_available"
    assert result["external_literature"]["result_count"] == 1
    record = result["external_literature"]["results"][0]
    assert record["doi"] == "10.1000/example"
    assert record["canonical_evidence"] is False
    assert record["review_state"] == "REVIEW_REQUIRED"


def test_external_literature_is_not_called_when_local_coverage_exists(monkeypatch):
    def _unexpected(*args, **kwargs):
        raise AssertionError("Europe PMC should not be queried")

    monkeypatch.setattr(external_literature.requests, "get", _unexpected)
    result = external_literature.augment_retrieval_with_external_literature(
        {
            "results": [{"title": "Indexed", "canonical_evidence": True}],
            "total_eligible_results": 1,
        },
        "Sarcochilus cold flowering",
    )
    assert result["external_literature"]["status"] == "not_needed_local_coverage_available"


def test_noaa_cpc_context_only_runs_for_climate_sensitive_questions(monkeypatch):
    calls = []

    def _get(url, **kwargs):
        calls.append(url)
        return _Response(text="<html><body>El Nino is forecast through winter. Above-normal precipitation is favored.</body></html>")

    monkeypatch.setattr(climate_context.requests, "get", _get)
    irrelevant = climate_context.build_seasonal_climate_context(
        "How does pollinia removal work in Cattleya?"
    )
    assert irrelevant["requested"] is False
    assert calls == []

    relevant = climate_context.build_seasonal_climate_context(
        "Will an El Niño wet winter affect Dendrobium flowering?"
    )
    assert relevant["requested"] is True
    assert relevant["status"] == "available"
    assert len(relevant["products"]) == 2
    assert "El Nino" in relevant["products"][0]["text"]
    assert relevant["products"][0]["canonical_orchid_evidence"] is False


def test_deterministic_provider_exposes_external_sources_without_promoting_them():
    provider = DeterministicGovernedReplyProvider()
    reply = provider.generate(
        messages=[
            {
                "role": "user",
                "content": "Compare Dendrobium and Sarcochilus winter flowering responses.",
            }
        ],
        governed_context={
            "casual": False,
            "retrieval": {
                "results": [],
                "external_literature": {
                    "results": [
                        {
                            "title": "Example orchid flowering paper",
                            "authors": "A. Author",
                            "publication_date": "2025",
                            "doi": "10.1000/orchid",
                            "abstract": "Cold treatment changed flowering response.",
                        }
                    ]
                },
            },
            "continuum": {"taxa": []},
            "climate": {
                "products": [
                    {
                        "product": "seasonal_outlook_discussion",
                        "text": "El Nino conditions are expected during winter.",
                    }
                ]
            },
            "mission": None,
            "mission_error": None,
        },
    )
    # SUPERSEDED wording, IDENTICAL guarantees. Provider names are machinery and
    # now live in the inspectable structure rather than the prose (the
    # conversational constitution keeps provider paths out of the answer). The
    # two epistemic guarantees this test exists for remain in the answer itself:
    # external literature is not promoted to canonical, and climate context does
    # not establish physiology.
    assert "hasn't been through Continuum review yet" in reply.text
    assert "provisional rather than as settled Continuum evidence" in reply.text
    assert "does not establish orchid physiological responses" in reply.text
    assert "not treating it as evidence for the biology" in reply.text
    # The external sources themselves stay exposed, just not promoted.
    assert "external_literature" in reply.synthesis_structure["cited_source_families"]
    assert "climate" in reply.synthesis_structure["cited_source_families"]
    assert reply.synthesis_structure["external_literature_review_required"] is True
