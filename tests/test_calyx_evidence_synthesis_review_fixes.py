from __future__ import annotations

from app.calyx_conversation.evidence_synthesis import build_synthesis_packet


def _packet(*, question: str = "How is CAM supported?", continuum=None, mission=None, retrieval=None):
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
