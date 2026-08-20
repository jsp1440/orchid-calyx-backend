from __future__ import annotations

import pytest

from app.calyx_conversation.evidence_synthesis import build_synthesis_packet


CASES = [
    ("taxonomy", "Why are two orchid names treated as synonyms, and which name should I use?"),
    ("physiology", "How can CAM physiology make sense for an orchid growing in a humid forest?"),
    ("ecology", "How might elevation, cloud cover, and epiphytic habit interact in this orchid's ecology?"),
    ("cultivation", "What does its native habitat imply for watering and nighttime temperature in cultivation?"),
    ("conservation", "Why might a narrowly distributed orchid be vulnerable even if some populations are locally abundant?"),
    ("literature_conflict", "Two papers disagree about the pollinator. What should we conclude?"),
    ("insufficient_evidence", "Does this orchid definitely require one specific mycorrhizal fungus to germinate?"),
    ("followup_context", "Which of those traits are probably adaptive rather than merely correlated?"),
    ("identification", "Which floral characters actually separate these two similar species?"),
    ("evolution", "Does repeated evolution of a similar floral form imply the same pollination mechanism?"),
]


def _context_for(question: str, category: str):
    supporting = [{
        "candidate_id": f"{category}-support",
        "subject": category.replace("_", " "),
        "predicate": "is informed by",
        "value": "the supplied canonical evidence and taxon-specific context",
    }]
    contradicting = []
    missing = []
    conclusion = f"The supplied evidence supports a qualified {category.replace('_', ' ')} interpretation rather than a source-by-source inventory."
    if category in {"literature_conflict", "evolution", "followup_context"}:
        contradicting = [{
            "candidate_id": f"{category}-limit",
            "subject": "strong generalization",
            "predicate": "is limited by",
            "value": "conflicting evidence or an alternative explanation",
        }]
    if category == "insufficient_evidence":
        missing = ["direct taxon-specific experimental evidence"]
        conclusion = "The evidence is insufficient for a definitive requirement claim."
    return {
        "retrieval": {
            "results": [{
                "result_id": f"{category}-canonical",
                "object_type": "LITERATURE",
                "title": f"Canonical {category} evidence",
                "authorized_excerpt": f"A governed record relevant to {category.replace('_', ' ')} and the biological question.",
            }],
            "external_literature": {"results": []},
        },
        "continuum": {
            "taxa": [{
                "genus": "Phalaenopsis",
                "environmental_facts": [{"statement": f"A canonical graph fact relevant to {category.replace('_', ' ')}."}],
            }],
        },
        "climate": {"products": []},
        "mission": {
            "mission_id": f"mission-{category}",
            "question": question,
            "supporting_evidence": supporting,
            "contradicting_evidence": contradicting,
            "missing_evidence": missing,
            "conclusions": [{"type": "inference", "text": conclusion}],
            "confidence": 0.7,
            "review_status": "HUMAN_REVIEW_REQUIRED",
        },
    }


@pytest.mark.parametrize("category,question", CASES)
def test_reasoning_graph_covers_realistic_orchid_question_classes(category, question):
    context = _context_for(question, category)
    packet = build_synthesis_packet(
        question=question,
        retrieval=context["retrieval"],
        continuum=context["continuum"],
        climate=context["climate"],
        mission=context["mission"],
        mission_error=None,
        interaction_context={"current_question": question},
    )
    assert packet["question"] == question
    assert packet["question_preserved"] is True
    assert packet["reasoning_graph"]["claims"]
    assert packet["reasoning_graph"]["edges"]
    assert packet["synthesis_plan"]["integrate_across_sources"] is True
    assert packet["synthesis_plan"]["do_not_narrate_sources_sequentially"] is True
    families = set(packet["reconciliation"]["source_families"])
    assert {"continuum_retrieval", "knowledge_graph", "brain_mission"}.issubset(families)
    if category in {"literature_conflict", "evolution", "followup_context"}:
        assert packet["reconciliation"]["unresolved_conflict"] is True
    if category == "insufficient_evidence":
        assert "direct taxon-specific experimental evidence" in packet["reconciliation"]["missing_evidence"]


def test_no_mission_turn_preserves_question_from_bounded_interaction_context():
    question = "What is unusual about this orchid's velamen?"
    packet = build_synthesis_packet(
        question="",
        retrieval={"results": []},
        continuum={},
        climate={},
        mission=None,
        mission_error=None,
        interaction_context={"current_question": question, "context_is_evidence": False},
    )
    assert packet["question"] == question
    assert packet["question_preserved"] is True
    assert packet["interaction_context"]["context_is_evidence"] is False


def test_claim_graph_maps_contradiction_to_claim_instead_of_separate_source_inventory():
    question = "Does repeated evolution of a similar floral form prove the same pollinator?"
    context = _context_for(question, "evolution")
    packet = build_synthesis_packet(
        question=question,
        retrieval=context["retrieval"], continuum=context["continuum"], climate={},
        mission=context["mission"], mission_error=None,
    )
    contradiction_edges = [edge for edge in packet["reasoning_graph"]["edges"] if edge["relation"] == "contradicts"]
    assert contradiction_edges
    claim_ids = {claim["claim_id"] for claim in packet["reasoning_graph"]["claims"]}
    assert all(edge["claim_id"] in claim_ids for edge in contradiction_edges)
