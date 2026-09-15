"""Tests for app.kalix.persona — KALIX-BUILD-002.

Verifies that KalixPersona:
  1. Wraps CALYX-PERSONA-005 without duplicating the constitution
  2. Operational domains include required scientific fields
  3. Depth adaptation classifies user signals correctly
  4. build_system_context composes Kalix header + Calyx constitution
  5. Singleton KALIX_PERSONA is accessible
"""
from __future__ import annotations

from app.kalix.persona import (
    DEPTH_LEVELS,
    KALIX_PERSONA,
    KALIX_PERSONA_VERSION,
    OPERATIONAL_DOMAINS,
    KalixPersona,
)

# ── 1. Singleton and version ──────────────────────────────────────────────────

def test_singleton_is_kalix_persona_instance() -> None:
    assert isinstance(KALIX_PERSONA, KalixPersona)


def test_version_string() -> None:
    assert KALIX_PERSONA_VERSION == "KALIX-PERSONA-001"
    assert KALIX_PERSONA.version == "KALIX-PERSONA-001"


# ── 2. Operational domains ───────────────────────────────────────────────────

def test_domain_count_at_least_ten() -> None:
    assert len(OPERATIONAL_DOMAINS) >= 10


def test_domain_includes_orchid_science() -> None:
    assert "orchid science" in OPERATIONAL_DOMAINS


def test_domain_includes_taxonomy() -> None:
    assert "taxonomy" in OPERATIONAL_DOMAINS


def test_domain_includes_conservation() -> None:
    assert "conservation" in OPERATIONAL_DOMAINS


def test_domain_includes_scientific_writing() -> None:
    assert "scientific writing" in OPERATIONAL_DOMAINS


def test_depth_levels_has_four_entries() -> None:
    assert set(DEPTH_LEVELS.keys()) == {"grower", "student", "scientist", "researcher"}


# ── 3. Depth adaptation ───────────────────────────────────────────────────────

def test_adapt_depth_default_is_grower() -> None:
    assert KALIX_PERSONA.adapt_depth("I love growing orchids") == "grower"


def test_adapt_depth_empty_string_is_grower() -> None:
    assert KALIX_PERSONA.adapt_depth("") == "grower"


def test_adapt_depth_student_signal() -> None:
    assert KALIX_PERSONA.adapt_depth("I am a student studying botany") == "student"


def test_adapt_depth_scientist_signal() -> None:
    assert KALIX_PERSONA.adapt_depth("I'm a botanist at a university") == "scientist"


def test_adapt_depth_researcher_signal() -> None:
    assert KALIX_PERSONA.adapt_depth("I'm a PhD researcher in my lab") == "researcher"


def test_adapt_depth_case_insensitive() -> None:
    assert KALIX_PERSONA.adapt_depth("I AM A STUDENT") == "student"


def test_adapt_depth_researcher_beats_student() -> None:
    # "researcher" outranks "student" when both appear; order in _DEPTH_SIGNALS ensures this
    result = KALIX_PERSONA.adapt_depth("postdoc student in the lab")
    assert result == "researcher"


# ── 4. System context composition ────────────────────────────────────────────

def test_build_system_context_contains_kalix_version() -> None:
    ctx = KALIX_PERSONA.build_system_context()
    assert "KALIX-PERSONA-001" in ctx


def test_build_system_context_contains_calyx_constitution() -> None:
    ctx = KALIX_PERSONA.build_system_context()
    # Calyx constitution is delegated to conversational_system_guidance()
    assert "CALYX-PERSONA-005" in ctx


def test_build_system_context_contains_depth_level() -> None:
    ctx = KALIX_PERSONA.build_system_context(depth_level="scientist")
    assert "scientist" in ctx


def test_build_system_context_contains_oc_modules() -> None:
    ctx = KALIX_PERSONA.build_system_context(oc_modules=["lexicon", "literature_extraction"])
    assert "lexicon" in ctx
    assert "literature_extraction" in ctx


def test_build_system_context_no_modules_note() -> None:
    ctx = KALIX_PERSONA.build_system_context(oc_modules=[])
    assert "without explicit OC module context" in ctx


def test_build_system_context_does_not_duplicate_constitution() -> None:
    ctx = KALIX_PERSONA.build_system_context()
    # The constitution appears exactly once (we delegate; never copy-paste it)
    count = ctx.count("CALYX-PERSONA-005")
    assert count == 1
