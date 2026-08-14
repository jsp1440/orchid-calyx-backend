from __future__ import annotations

from app.calyx_conversation.persona import CALYX_CONVERSATIONAL_CONSTITUTION
from app.calyx_conversation.provider_runtime import (
    OpenAIRuntimeResponsesProvider,
    runtime_provider_configuration,
)
from app.calyx_conversation.speak_routes import (
    ConversationTurnRequest,
    _deliverable_capabilities,
    _effective_retrieval_limit,
    _external_citations,
)


def test_long_research_turn_accepts_well_beyond_old_limits():
    payload = ConversationTurnRequest(message="x" * 90000)
    assert len(payload.message) == 90000


def test_deep_research_automatically_expands_retrieval_budget():
    question = (
        "Conduct a formal evidence-grounded literature review of the peer-reviewed scientific literature "
        "and provide DOI and PMID identifiers. " * 12
    )
    assert _effective_retrieval_limit(question, 8) >= 20


def test_external_citations_preserve_identifiers_and_review_boundary():
    citations = _external_citations(
        {
            "external_literature": {
                "results": [
                    {
                        "title": "Orchid physiology paper",
                        "authors": "A. Author",
                        "publication_date": "2024-01-01",
                        "journal": "Plants",
                        "doi": "10.1000/example",
                        "pmid": "12345",
                        "source": "Europe PMC",
                        "review_state": "REVIEW_REQUIRED",
                        "canonical_evidence": False,
                    }
                ]
            }
        }
    )
    assert citations == [
        {
            "title": "Orchid physiology paper",
            "authors": "A. Author",
            "publication_date": "2024-01-01",
            "journal": "Plants",
            "doi": "10.1000/example",
            "pmid": "12345",
            "pmcid": None,
            "provider": "Europe PMC",
            "review_state": "REVIEW_REQUIRED",
            "canonical_evidence": False,
        }
    ]


def test_persona_requires_autonomous_authorized_research_and_provider_honesty():
    assert "must continue through the available research workflow without asking for a second confirmation" in CALYX_CONVERSATIONAL_CONSTITUTION
    assert "Never claim access to Web of Science, Google Scholar, Scopus" in CALYX_CONVERSATIONAL_CONSTITUTION
    assert "Do not make a stronger claim than the retrieved source supports" in CALYX_CONVERSATIONAL_CONSTITUTION


def test_deliverable_contract_is_truthful_about_rendering():
    capabilities = _deliverable_capabilities()
    assert capabilities["downloadable_conversation_export"] is True
    assert capabilities["structured_citations"] is True
    assert capabilities["chart_ready_tables"] is True
    assert capabilities["map_ready_occurrence_data"] is True
    assert capabilities["native_chart_rendering_from_answer"] is True
    assert capabilities["native_map_rendering_from_answer"] is True
    assert capabilities["map_rendering_mode"] == "latitude_longitude_occurrence_plot"
    assert capabilities["sourced_image_rendering_from_answer"] is True
    assert capabilities["native_image_generation"] is False
    assert capabilities["artifact_block_formats"] == ["calyx-chart", "calyx-map", "calyx-image"]


def test_output_budget_is_large_and_configurable(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("CALYX_AGENT_MODEL", "gpt-test")
    monkeypatch.delenv("CALYX_CHAT_MAX_TOKENS", raising=False)
    provider = OpenAIRuntimeResponsesProvider(model="gpt-test", api_key="test-key")
    assert provider.max_tokens == 12000
    configuration = runtime_provider_configuration()
    assert configuration["max_output_tokens"] == 12000
    assert configuration["output_budget_configurable"] is True
    assert configuration["word_count_limit"] is False
