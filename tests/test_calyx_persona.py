from __future__ import annotations

from app.calyx_conversation.persona import (
    CALYX_CONVERSATIONAL_CONSTITUTION,
    CALYX_PERSONA_VERSION,
    FCOS_VOICE_MODE,
)
from app.calyx_conversation.provider import _scientific_system_prompt


def test_calyx_persona_has_stable_version_and_core_traits():
    assert CALYX_PERSONA_VERSION == "CALYX-PERSONA-001"
    text = CALYX_CONVERSATIONAL_CONSTITUTION.casefold()
    for phrase in (
        "warm",
        "curious",
        "botanically sophisticated",
        "scientific colleague",
        "trauma-informed",
        "gently whimsical",
        "finds biology fascinating",
    ):
        assert phrase in text


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
    assert "fcos voice" in prompt
    assert "do not publish" in prompt
