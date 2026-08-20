from __future__ import annotations

import json

from app.calyx_conversation.evidence_synthesis import (
    SYNTHESIS_CONTRACT_VERSION,
    build_synthesis_packet,
)
from app.calyx_conversation.provider_runtime import (
    OpenAIRuntimeResponsesProvider,
    runtime_provider_configuration,
)


def _packet(
    *,
    question: str = "How is CAM supported?",
    continuum=None,
    mission=None,
    retrieval=None,
):
    return build_synthesis_packet(
        question=question,
        retrieval=retrieval or {"results": []},
        continuum=continuum or {},
        climate={},
        mission=mission,
        mission_error=None,
    )


def test_contradiction_only_claim_is_not_reported_supported():
    packet = _packet(
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
        }
    )
    coverage = {item["claim_id"]: item for item in packet["reasoning_graph"]["coverage"]}
    assert coverage["question:0"]["coverage"] == "contradicted"
    assert coverage["question:0"]["supporting_or_informing_count"] == 0
    assert coverage["question:0"]["contradicting_count"] >= 1


def test_graph_nodes_edges_brain_graph_and_semantic_links_survive_normalization():
    packet = _packet(
        question="What pollinator relationship is recorded for Phalaenopsis?",
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
    )
    items = packet["evidence_items"]
    statements = "\n".join(str(item.get("statement") or "") for item in items)
    types = {item["evidence_type"] for item in items}

    assert "POLLINATED_BY" in statements
    assert "pollinator:moth-1" in statements
    assert "moth pollination reported" in statements
    assert "pollination syndrome" in statements
    assert "canonical_knowledge_graph_edge" in types
    assert "canonical_brain_graph_node" in types
    assert "approved_semantic_link" in types


def test_runtime_uses_current_user_message_without_interaction_context_or_mission():
    provider = OpenAIRuntimeResponsesProvider(model="test-model", api_key="test-key")
    question = "How does CAM physiology help an epiphytic orchid conserve water?"
    payload = provider._responses_payload(
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


def test_runtime_reports_the_implemented_synthesis_contract_version():
    configuration = runtime_provider_configuration()
    assert configuration["semantic_evidence_contract"] == SYNTHESIS_CONTRACT_VERSION
