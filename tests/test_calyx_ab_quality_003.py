from __future__ import annotations

import re

import pytest

from app.calyx_conversation.provider import DeterministicGovernedReplyProvider


QUESTIONS = [
    "Why can CAM physiology still be useful to a Phalaenopsis growing in a humid forest?",
    "Which floral traits best separate two closely related orchid species?",
    "What should I conclude when two papers report different pollinators?",
    "What does a cool high-elevation habitat imply for cultivation?",
    "Does a narrow geographic range automatically mean an orchid is endangered?",
    "Can we infer adaptation from a correlation between elevation and leaf thickness?",
    "What evidence would justify saying one mycorrhizal fungus is required for germination?",
    "How should a follow-up answer distinguish the traits we discussed as adaptive versus merely correlated?",
]


def _context(question: str, index: int):
    return {
        "casual": False,
        "interaction_context": {"current_question": question, "context_is_evidence": False},
        "retrieval": {
            "results": [{
                "result_id": f"r{index}",
                "object_type": "LITERATURE",
                "title": "Relevant governed evidence",
                "authorized_excerpt": "The evidence supports a biological relationship but does not justify an unlimited generalization.",
            }],
            "external_literature": {"results": []},
        },
        "continuum": {
            "taxa": [{"genus": "Phalaenopsis", "environmental_facts": [{"statement": "The taxon-specific graph context supplies relevant ecological information."}]}],
        },
        "climate": {"products": []},
        "mission": {
            "mission_id": f"m{index}",
            "question": question,
            "supporting_evidence": [{
                "candidate_id": f"s{index}",
                "subject": "the biological interpretation",
                "predicate": "is supported by",
                "value": "the supplied taxon-specific evidence",
            }],
            "contradicting_evidence": [{
                "candidate_id": f"c{index}",
                "subject": "an overly broad conclusion",
                "predicate": "is limited by",
                "value": "variation, alternative explanations, or incomplete comparative evidence",
            }],
            "conclusions": [{
                "type": "inference",
                "text": "The best-supported interpretation is biologically plausible, but it should remain taxon-specific and qualified rather than being generalized beyond the evidence.",
            }],
            "missing_evidence": ["direct comparative evidence needed for the strongest causal or universal claim"],
            "confidence": 0.72,
            "review_status": "HUMAN_REVIEW_REQUIRED",
            "sources": [],
        },
        "mission_error": None,
        "epistemic_policy": {"continuum_first": True},
        "deliverable_capabilities": {},
        "provider_configuration": {"selected": "deterministic-governed"},
    }


def _legacy_inventory_answer(context):
    retrieval = context["retrieval"]
    continuum = context["continuum"]
    mission = context["mission"]
    return (
        f"I found {len(retrieval['results'])} eligible Orchid Continuum evidence objects. "
        f"Knowledge Graph nodes were returned for {continuum['taxa'][0]['genus']}. "
        f"The Brain mission returned {len(mission['supporting_evidence'])} supporting records and "
        f"{len(mission['contradicting_evidence'])} contradicting records. "
        f"Missing evidence: {mission['missing_evidence'][0]}."
    )


def _score(answer: str, question: str) -> dict[str, int]:
    lower = answer.casefold()
    q_terms = {word for word in re.findall(r"[a-z]{4,}", question.casefold()) if word not in {"what", "when", "which", "does", "should", "from", "that", "this", "with"}}
    overlap = sum(1 for term in q_terms if term in lower)
    inventory_markers = ("eligible orchid continuum evidence objects", "knowledge graph nodes", "brain mission returned")
    integration = 2 if not any(marker in lower for marker in inventory_markers) and ("conclusion" in lower or "interpretation" in lower) else 0
    contextuality = 2 if overlap >= 2 else 1 if overlap else 0
    completeness = 2 if any(term in lower for term in ("limit", "missing", "incomplete", "qualif")) else 0
    caution = 2 if any(term in lower for term in ("provisional", "qualified", "does not", "remain", "inference")) else 0
    conversational = 2 if not any(marker in lower for marker in inventory_markers) and len(answer.split()) >= 20 else 0
    return {
        "integration": integration,
        "contextuality": contextuality,
        "completeness": completeness,
        "scientific_caution": caution,
        "conversational_quality": conversational,
    }


def _total(scores):
    return sum(scores.values())


@pytest.mark.parametrize("index,question", list(enumerate(QUESTIONS)))
def test_semantic_fallback_outscores_legacy_source_inventory(index, question):
    context = _context(question, index)
    semantic = DeterministicGovernedReplyProvider().generate(messages=[{"role": "user", "content": question}], governed_context=context).text
    legacy = _legacy_inventory_answer(context)
    semantic_score = _score(semantic, question)
    legacy_score = _score(legacy, question)
    assert semantic_score["integration"] > legacy_score["integration"]
    assert semantic_score["scientific_caution"] >= legacy_score["scientific_caution"]
    assert _total(semantic_score) >= _total(legacy_score) + 2
    assert "Knowledge Graph nodes" not in semantic
    assert "Brain mission returned" not in semantic
