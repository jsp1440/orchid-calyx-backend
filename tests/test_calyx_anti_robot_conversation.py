"""ANTI-ROBOT REGRESSION CONTRACT.

These tests fail if Calyx regresses to source-inventory behaviour: reporting
each subsystem separately and leaving the user to integrate the facts.

They pin BEHAVIOUR, not wording. Each asserts a property the conversational
contract requires (integration, responsiveness, honest degradation, contradiction
preserved, unavailable != zero), so the prose can be improved freely without
rewriting the suite -- but it cannot go back to being a database dump.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from app.calyx_conversation.conversational_synthesis import (
    compose_conversational_answer,
    is_follow_up,
    resolve_subject,
)
from app.calyx_conversation.evidence_synthesis import build_synthesis_packet
from app.calyx_conversation.provider import DeterministicGovernedReplyProvider

QUESTION = (
    "Why would an orchid growing as an epiphyte benefit from velamen, and how do "
    "the anatomy, physiology and habitat fit together?"
)

# Three DIFFERENT source families bearing on one biological question.
RETRIEVAL = {
    "results": [
        {
            "object_type": "trait_record",
            "title": "Velamen radicum",
            "authorized_excerpt": "Aerial roots bear a multi-layered dead epidermal velamen.",
        },
        {
            "object_type": "habitat_record",
            "title": "Epiphytic canopy habitat",
            "authorized_excerpt": "Canopy substrates dry within hours of rainfall.",
        },
    ],
    "total_eligible_results": 2,
    "external_literature": {
        "status": "available",
        "result_count": 1,
        "results": [
            {
                "title": "Water uptake by the velamen radicum",
                "abstract": "Velamen wets rapidly on contact with liquid water.",
                "doi": "10.1000/test",
                "source": "Europe PMC",
                "review_state": "REVIEW_REQUIRED",
            }
        ],
    },
}

CONTINUUM = {
    "candidate_genera": ["Phalaenopsis"],
    "resolved_genera": ["Phalaenopsis"],
    "taxa": [{"genus": "Phalaenopsis"}],
    "diagnostics": [],
}

CLIMATE = {"requested": False, "status": "not_relevant", "products": []}

MISSION = {
    "mission_id": "mission-anti-robot",
    "state": "COMPLETED",
    "confidence": 0.6,
    "supporting_evidence": [
        {"subject": "velamen", "predicate": "absorbs", "value": "liquid water rapidly"},
        {"subject": "epiphytic habitat", "predicate": "provides", "value": "intermittent water"},
    ],
    "contradicting_evidence": [
        {
            "subject": "velamen thickness",
            "predicate": "does not predict",
            "value": "drought tolerance across all taxa",
        }
    ],
    "missing_evidence": ["direct velamen conductance measurements"],
    "sources": [],
    "artifacts": {"evidence_packet_id": "ep-anti-robot"},
}

# Labels the previous composer emitted, one per subsystem. Their return would be
# the regression this suite exists to catch.
SOURCE_INVENTORY_LABELS = (
    "Evidence summary:",
    "Supporting evidence count:",
    "Orchid Continuum context:",
    "External literature context:",
    "Climate context:",
    "Governed provenance:",
    "Evidence vs inference:",
    "Strength of evidence:",
    "Disagreements or conflicting evidence:",
)


def packet_for(question: str = QUESTION, **overrides):
    kwargs = {
        "question": question,
        "retrieval": RETRIEVAL,
        "continuum": CONTINUUM,
        "climate": CLIMATE,
        "mission": MISSION,
        "mission_error": None,
    }
    kwargs.update(overrides)
    return build_synthesis_packet(**kwargs)


def compose(**kwargs):
    return compose_conversational_answer(packet=packet_for(), **kwargs)


def test_answer_is_not_a_per_subsystem_inventory():
    answer = compose().text
    for label in SOURCE_INVENTORY_LABELS:
        assert label not in answer, f"source-inventory block returned: {label}"


def test_answer_integrates_evidence_from_more_than_one_source_family():
    composed = compose()
    assert composed.structure["integrated_across_source_families"] is True
    # At least one claim must carry evidence from more than one subsystem, and
    # that claim must actually be spoken in the answer rather than tabulated.
    multi = [
        entry
        for entry in composed.structure["claim_coverage"]
        if len(entry["source_families"]) > 1
    ]
    assert multi, "no claim combined evidence across source families"
    assert composed.text.strip()


def test_answer_leads_with_a_conclusion_not_a_source_listing():
    first_paragraph = compose().text.split("\n\n")[0]
    assert first_paragraph
    # The opening must not begin by naming a subsystem.
    for prefix in ("Retrieval", "The knowledge graph", "Taxonomy says", "Literature says"):
        assert not first_paragraph.startswith(prefix)


def test_machinery_stays_out_of_the_prose():
    composed = compose()
    for leak in ("mission-anti-robot", "ep-anti-robot", "0.6", "evidence_id", "source_family"):
        assert leak not in composed.text, f"internal machinery leaked into prose: {leak}"
    # It remains inspectable, just not in the conversation.
    assert composed.structure["claim_coverage"]


def test_contradiction_is_never_rendered_as_support():
    composed = compose()
    contested = [
        entry for entry in composed.structure["claim_coverage"] if entry["contradicting_count"]
    ]
    assert contested, "contradicting evidence disappeared from the coverage map"
    assert composed.structure["unresolved_conflict"] is True
    lowered = composed.text.lower()
    assert "isn't all pointing one way" in lowered or "hold the conclusion loosely" in lowered


def test_unavailable_evidence_is_not_reported_as_zero_or_absence():
    composed = compose_conversational_answer(
        packet=packet_for(
            retrieval={"results": [], "total_eligible_results": 0},
            mission=None,
        ),
    )
    text = composed.text.lower()
    assert "not evidence of absence" in text or "not an indication that the biology" in text
    # An empty index must never be phrased as a measured zero.
    assert "0 " not in composed.text
    assert "no evidence exists" not in text


def test_missing_evidence_is_named_rather_than_hidden():
    composed = compose()
    assert composed.structure["missing_evidence"]
    assert "conductance" in composed.text


def test_provider_failure_degrades_honestly_without_fabricating_intelligence():
    composed = compose_conversational_answer(
        packet=packet_for(), mission_error="BRAIN_MISSION_UNAVAILABLE"
    )
    assert composed.structure["mission_unavailable"] is True
    lowered = composed.text.lower()
    assert "couldn't complete" in lowered
    assert "not a finding about the biology" in lowered
    # Nothing may be presented as established when the evidence run failed.
    assert "the evidence supports" not in lowered


def test_degraded_composition_discloses_that_it_is_not_full_reasoning():
    assert "generative reasoning path wasn't available" in compose(generative=False).text
    assert "generative reasoning path wasn't available" not in compose(generative=True).text


class TestConversationalContinuity:
    HISTORY: ClassVar[list[dict[str, str]]] = [
        {"role": "user", "content": QUESTION},
        {"role": "assistant", "content": "A prior Calyx answer."},
    ]

    @pytest.mark.parametrize(
        "turn", ["Why?", "So what does that mean?", "What evidence is that based on?"]
    )
    def test_follow_ups_are_recognised(self, turn):
        assert is_follow_up(turn) is True

    def test_a_substantive_question_is_not_treated_as_a_follow_up(self):
        assert is_follow_up(QUESTION) is False

    def test_follow_up_resolves_the_prior_subject(self):
        assert resolve_subject("Why?", self.HISTORY) == QUESTION

    def test_prior_assistant_statements_are_never_the_subject_of_record(self):
        history = [
            {"role": "user", "content": QUESTION},
            {"role": "assistant", "content": "Velamen is definitely an adaptation."},
        ]
        assert resolve_subject("Why?", history) == QUESTION

    def test_follow_up_answer_names_the_investigation_it_continues(self):
        composed = compose_conversational_answer(
            packet=packet_for(),
            history=self.HISTORY,
            resolved_subject=QUESTION,
            follow_up=True,
        )
        assert composed.structure["follow_up_turn"] is True
        assert composed.text.startswith("Staying with")
        assert "velamen" in composed.text.lower()

    def test_a_referential_turn_never_becomes_a_claim_heading(self):
        composed = compose_conversational_answer(
            packet=packet_for(question="Why?"),
            resolved_subject=QUESTION,
            follow_up=True,
        )
        assert "On why:" not in composed.text


def test_user_questions_remain_interaction_context_not_scientific_evidence():
    packet = packet_for()
    families = {item.get("source_family") for item in packet["evidence_items"]}
    assert "user_question" not in families
    assert "interaction_context" not in families


def test_deterministic_provider_uses_the_conversational_composer():
    reply = DeterministicGovernedReplyProvider().generate(
        messages=[{"role": "user", "content": QUESTION}],
        governed_context={
            "casual": False,
            "retrieval": RETRIEVAL,
            "continuum": CONTINUUM,
            "climate": CLIMATE,
            "mission": MISSION,
        },
    )
    for label in SOURCE_INVENTORY_LABELS:
        assert label not in reply.text
    assert reply.synthesis_structure is not None
    # Provenance stays inspectable even though it left the prose.
    assert reply.synthesis_structure["governed_provenance"]["evidence_packet_id"] == "ep-anti-robot"
    assert reply.synthesis_structure["degraded_composition"] is True


def test_sources_and_provenance_remain_inspectable():
    reply = DeterministicGovernedReplyProvider().generate(
        messages=[{"role": "user", "content": QUESTION}],
        governed_context={
            "casual": False,
            "retrieval": RETRIEVAL,
            "continuum": CONTINUUM,
            "climate": CLIMATE,
            "mission": {
                **MISSION,
                "sources": [
                    {
                        "title": "Orchid root anatomy",
                        "citation": {"document_title": "Orchid root anatomy", "locator": "p. 14"},
                    }
                ],
            },
        },
    )
    assert any("Orchid root anatomy" in item for item in reply.synthesis_structure["citations"])


def test_unsupported_synthesis_is_not_invented():
    """With no linked evidence the composer must decline, not narrate."""

    composed = compose_conversational_answer(
        packet=build_synthesis_packet(
            question="Does velamen thickness cause drought tolerance?",
            retrieval={"results": [], "total_eligible_results": 0},
            continuum={"taxa": [], "resolved_genera": [], "diagnostics": []},
            climate=CLIMATE,
            mission=None,
            mission_error=None,
        ),
    )
    lowered = composed.text.lower()
    assert "can't answer that from evidence yet" in lowered
    for invented in ("because", "therefore", "this shows that"):
        assert invented not in lowered
