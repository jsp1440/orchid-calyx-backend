from __future__ import annotations

from app.calyx_conversation.persona import (
    CALYX_CONVERSATIONAL_CONSTITUTION,
    CALYX_PERSONA_VERSION,
    FCOS_VOICE_MODE,
)
from app.calyx_conversation.provider import _scientific_system_prompt


def test_calyx_persona_has_stable_version_and_core_traits():
    assert CALYX_PERSONA_VERSION == "CALYX-PERSONA-005"
    text = CALYX_CONVERSATIONAL_CONSTITUTION.casefold()
    for phrase in (
        "warm",
        "curious",
        "botanically sophisticated",
        "scientific colleague",
        "trauma-informed",
        "gently whimsical",
        "finds biology fascinating",
        "answer-first rule",
    ):
        assert phrase in text


def test_calyx_answer_first_policy_blocks_workflow_menus_and_graph_limit_inference():
    text = CALYX_CONVERSATIONAL_CONSTITUTION.casefold()
    assert "answer the user's question directly" in text
    assert "do not present a menu" in text
    assert "should not make the user manage internal evidence workflows" in text
    assert "40 nodes returned" in text
    assert "must never be converted into an estimate of species richness" in text
    assert "should not ask unnecessary spelling or intent confirmations" in text
    assert "literature retrieval should enrich or qualify the answer, not act as a veto" in text


def test_fcos_voice_is_separate_publication_mode():
    text = FCOS_VOICE_MODE.casefold()
    assert "publication and outreach mode" in text
    assert "not calyx's permanent identity" in text
    assert "scientifically accurate" in text
    assert "whimsical" in text


def test_generative_system_prompt_includes_persona_and_governance():
    prompt = _scientific_system_prompt().casefold()
    assert "governed scientific collaborator" in prompt
    assert "calyx conversational constitution" in prompt
    assert "trauma-informed" in prompt
    assert "explains rather than lectures" in prompt
    assert "internal machinery" in prompt
    assert "answer-first rule" in prompt
    assert "fcos voice" in prompt
    assert "do not publish" in prompt
