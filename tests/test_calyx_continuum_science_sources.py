from __future__ import annotations

import json

from app.calyx_conversation import climate_context, external_literature, provider
from app.calyx_conversation.evidence_synthesis import (
    SYNTHESIS_CONTRACT_VERSION,
    build_synthesis_packet,
)
from app.calyx_conversation.literature_ingest import document_from_external_record
from app.calyx_conversation.provider_runtime import (
    OpenAIRuntimeResponsesProvider,
    configured_runtime_provider,
    runtime_provider_configuration,
)
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
    assert any("temperature" in query.casefold() for query in queries)
    assert all(len(query) < 500 for query in queries)


def test_physiology_relevance_ranking_demotes_scent_and_color_distractors():
    question = (
        "Dendrobium winter rest cold temperature floral induction drought keiki hormone"
    )
    relevant = {
        "title": "Low temperature controls floral induction in Dendrobium",
        "abstract": (
            "Cold treatment and water deficit altered flower bud differentiation and "
            "subsequent vegetative growth."
        ),
    }
    distractor = {
        "title": "Floral volatile and scent profiling in Dendrobium",
        "abstract": "Volatile terpenoids changed during open flower development.",
    }
    assert external_literature._relevance_score(
        relevant, question
    ) > external_literature._relevance_score(distractor, question)


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


def test_runtime_provider_autodetects_existing_openai_key_and_generic_model(monkeypatch):
    monkeypatch.delenv("CALYX_CHAT_COMPLETIONS_URL", raising=False)
    monkeypatch.delenv("CALYX_CHAT_MODEL", raising=False)
    monkeypatch.delenv("CALYX_AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("CALYX_AGENT_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-runtime-model")

    configured = configured_runtime_provider()
    status = runtime_provider_configuration()

    assert isinstance(configured, OpenAIRuntimeResponsesProvider)
    assert configured.model == "test-runtime-model"
    assert status["generative_ready"] is True
    assert status["selected"] == "openai-runtime-autodetect"
    assert status["secrets_exposed"] is False


def test_runtime_provider_diagnoses_missing_model_without_exposing_secret(monkeypatch):
    monkeypatch.delenv("CALYX_CHAT_COMPLETIONS_URL", raising=False)
    monkeypatch.delenv("CALYX_CHAT_MODEL", raising=False)
    monkeypatch.delenv("CALYX_AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("CALYX_AGENT_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")

    status = runtime_provider_configuration()

    assert status["generative_ready"] is False
    assert "CALYX_AGENT_MODEL or OPENAI_MODEL" in status["missing_configuration"]
    assert "secret-value" not in repr(status)


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


def test_live_research_bridge_document_is_brain_eligible_but_review_bound():
    record = {
        "title": "Cold treatment and flower bud differentiation in Dendrobium",
        "abstract": "Low temperature altered subsequent flower bud differentiation.",
        "authors": "Example A",
        "publication_date": "2022-01-01",
        "doi": "10.0000/brain-example",
        "pmid": "67890",
        "pmcid": None,
        "matched_query": '"Dendrobium" AND "low temperature"',
        "relevance_score": 18.0,
    }
    document = document_from_external_record(
        record, query="Dendrobium winter flowering"
    )
    assert document is not None
    assert "BRAIN" in document.intended_consumers
    assert document.verification_state == "UNVERIFIED"
    assert document.display_policy == "LIMITED_PREVIEW_ONLY"
    assert document.source_anchor_ids
    assert document.metadata["scientific_review_required"] is True
    assert document.metadata["relevance_score"] == 18.0


def test_contradiction_only_claim_is_not_reported_as_supported():
    packet = build_synthesis_packet(
        question="Is CAM absent in this orchid?",
        retrieval={"results": []},
        continuum={},
        climate={},
        mission={
            "mission_id": "m1",
            "question": "Is CAM absent in this orchid?",
            "supporting_evidence": [],
            "contradicting_evidence": [
                {
                    "subject": "CAM",
                    "predicate": "is present in",
                    "value": "the sampled orchid",
                }
            ],
            "conclusions": [],
            "missing_evidence": [],
        },
        mission_error=None,
    )
    coverage = {
        item["claim_id"]: item for item in packet["reasoning_graph"]["coverage"]
    }
    assert coverage["question:0"]["coverage"] == "contradicted"
    assert coverage["question:0"]["supporting_or_informing_count"] == 0
    assert coverage["question:0"]["contradicting_count"] >= 1


def test_graph_and_semantic_records_survive_synthesis_normalization():
    packet = build_synthesis_packet(
        question="What pollinator relationship is recorded for Phalaenopsis?",
        retrieval={"results": []},
        continuum={
            "taxa": [
                {
                    "genus": "Phalaenopsis",
                    "knowledge_graph": {
                        "nodes": [
                            {
                                "canonical_key": "taxon:phalaenopsis",
                                "node_type": "taxon",
                                "properties": {"growth_habit": "epiphytic"},
                            }
                        ],
                        "edges": [
                            {
                                "canonical_key": "edge:pollinator-1",
                                "edge_type": "POLLINATED_BY",
                                "source": "taxon:phalaenopsis",
                                "target": "pollinator:moth-1",
                                "properties": {"evidence": "field observation"},
                            }
                        ],
                    },
                    "brain_graph": {
                        "nodes": [
                            {
                                "canonical_key": "brain:pollination-claim",
                                "node_type": "claim",
                                "properties": {"text": "moth pollination reported"},
                            }
                        ]
                    },
                    "environmental_facts": [],
                }
            ],
            "semantic_links": [
                {
                    "concept": "pollination syndrome",
                    "target": "lexicon:pollination-syndrome",
                    "review_state": "APPROVED",
                }
            ],
        },
        climate={},
        mission=None,
        mission_error=None,
    )
    statements = "\n".join(
        str(item.get("statement") or "") for item in packet["evidence_items"]
    )
    types = {item["evidence_type"] for item in packet["evidence_items"]}
    assert "POLLINATED_BY" in statements
    assert "pollinator:moth-1" in statements
    assert "moth pollination reported" in statements
    assert "pollination syndrome" in statements
    assert "canonical_knowledge_graph_edge" in types
    assert "canonical_brain_graph_node" in types
    assert "approved_semantic_link" in types


def test_runtime_synthesis_uses_current_user_message_without_mission_context():
    runtime = OpenAIRuntimeResponsesProvider(model="test-model", api_key="test-key")
    question = "How does CAM physiology help an epiphytic orchid conserve water?"
    payload = runtime._responses_payload(
        messages=[{"role": "user", "content": question}],
        governed_context={
            "casual": False,
            "retrieval": {"results": []},
            "continuum": {},
            "climate": {},
            "mission": None,
            "mission_error": None,
            "interaction_context": {},
            "epistemic_policy": {},
            "deliverable_capabilities": {},
            "provider_configuration": {},
        },
    )
    semantic_text = payload["input"][-1]["content"][0]["text"]
    prefix = "Governed Calyx semantic synthesis context for this turn:\n"
    semantic = json.loads(semantic_text.removeprefix(prefix))
    assert semantic["synthesis_packet"]["question"] == question
    assert semantic["synthesis_packet"]["question_preserved"] is True
    assert semantic["synthesis_packet"]["reasoning_graph"]["claims"]


def test_runtime_reports_current_synthesis_contract_version():
    status = runtime_provider_configuration()
    assert status["semantic_evidence_contract"] == SYNTHESIS_CONTRACT_VERSION
