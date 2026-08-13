from __future__ import annotations

from app.calyx_conversation import climate_context, external_literature, provider
from scripts.calyx_literature_backfill import _document


def test_long_orchid_prompt_is_decomposed_into_targeted_literature_queries():
    prompt = (
        "Compare Dendrobium and Sarcochilus winter flowering, cold temperature, "
        "dormancy, drought, floral induction, hormones and keiki production."
    )
    queries = external_literature._query_plan(prompt)
    assert queries
    assert queries[0].startswith('"Dendrobium"')
    assert any(query.startswith('"Sarcochilus"') for query in queries)
    assert any("flower" in query.casefold() for query in queries)
    assert all(len(query) < 500 for query in queries)


def test_climate_summary_prefers_forecast_sentences_over_navigation():
    text = (
        "Site Map Organization Search Search by city or zip code. "
        "El Nino conditions are expected to continue through winter. "
        "Above-normal precipitation is favored for parts of California during DJF. "
        "Our Mission Who We Are Contact Us. "
        "Temperature probabilities favor above-normal conditions in the Southwest."
    )
    points = climate_context._summary_points(text)
    joined = " ".join(points).casefold()
    assert "el nino" in joined
    assert "precipitation" in joined
    assert "california" in joined
    assert "site map" not in joined
    assert "our mission" not in joined


def test_speak_reuses_existing_calyx_agent_openai_configuration(monkeypatch):
    monkeypatch.delenv("CALYX_CHAT_COMPLETIONS_URL", raising=False)
    monkeypatch.delenv("CALYX_CHAT_MODEL", raising=False)
    monkeypatch.setenv("CALYX_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("CALYX_AGENT_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    configured = provider.configured_reply_provider()
    assert isinstance(configured, provider.OpenAIResponsesReplyProvider)
    assert configured.model == "test-model"


def test_literature_backfill_has_exact_anchor_and_bounded_preview():
    record = {
        "title": "Temperature and flowering in Dendrobium",
        "abstract": "Cold exposure changed subsequent flowering behavior in the experimental plants.",
        "authors": "Example A",
        "publication_date": "2020-01-01",
        "doi": "10.0000/example",
        "pmid": "12345",
        "pmcid": None,
    }
    document = _document(record, query="Dendrobium flowering temperature")
    assert document is not None
    assert document.source_anchor_ids
    assert document.display_policy == "LIMITED_PREVIEW_ONLY"
    assert document.metadata["excerpt_limit"] == 700
    assert isinstance(document.metadata["locator"], dict)
    anchor = str(document.source_anchor_ids[0])
    assert document.metadata["anchor_locators"][anchor] == document.metadata["locator"]
