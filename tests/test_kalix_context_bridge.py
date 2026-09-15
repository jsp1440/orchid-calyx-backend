"""Tests for app.kalix.context_bridge — KALIX-BUILD-001.

Verifies that the context bridge:
  1. Delegates retrieval to build_knowledge_context (no duplication)
  2. Adds Kalix persona context on top
  3. Maintains governance invariants
  4. Passes depth level and oc_modules through
  5. Fails gracefully when the underlying bridge fails
"""
from __future__ import annotations

from typing import Any

from app.kalix.context_bridge import build_kalix_context

# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_loader(entries: list[dict[str, Any]]) -> Any:
    def loader(*, q: str, limit: int) -> list[dict[str, Any]]:
        return entries

    return loader


ORCHID_ENTRY: dict[str, Any] = {
    "preferred_term": "Dendrobium",
    "quick_definition": "Large genus of orchids.",
    "expanded_definition": "Over 1800 accepted species.",
    "synonyms": ["Den."],
    "maturity": ["established"],
    "provenance": {"source": "OC Registry", "validation_status": "APPROVED"},
    "review_state": "APPROVED",
}


# ── 1. Knowledge context is included ─────────────────────────────────────────

def test_build_kalix_context_schema_present() -> None:
    ctx = build_kalix_context(
        "Dendrobium care",
        lexicon_loader=_mock_loader([]),
    )
    assert ctx["schema"] == "oc.calyx-knowledge-context.v1"


def test_build_kalix_context_lexicon_passed_through() -> None:
    ctx = build_kalix_context(
        "Dendrobium culture",
        lexicon_loader=_mock_loader([ORCHID_ENTRY]),
    )
    assert "lexicon" in ctx
    assert ctx["lexicon"]["source"] == "oc_lexicon"


def test_build_kalix_context_literature_key_present() -> None:
    ctx = build_kalix_context(
        "orchid roots",
        lexicon_loader=_mock_loader([]),
    )
    assert "literature" in ctx


# ── 2. Kalix persona context is added ────────────────────────────────────────

def test_kalix_persona_context_key_present() -> None:
    ctx = build_kalix_context("orchid", lexicon_loader=_mock_loader([]))
    assert "kalix_persona_context" in ctx


def test_kalix_persona_context_persona_version() -> None:
    ctx = build_kalix_context("orchid", lexicon_loader=_mock_loader([]))
    assert ctx["kalix_persona_context"]["persona_version"] == "KALIX-PERSONA-001"


# ── 3. Depth level and oc_modules pass through ───────────────────────────────

def test_default_depth_level_is_grower() -> None:
    ctx = build_kalix_context("orchid", lexicon_loader=_mock_loader([]))
    assert ctx["kalix_persona_context"]["depth_level"] == "grower"


def test_custom_depth_level_scientist() -> None:
    ctx = build_kalix_context(
        "orchid", depth_level="scientist", lexicon_loader=_mock_loader([])
    )
    assert ctx["kalix_persona_context"]["depth_level"] == "scientist"


def test_custom_depth_level_researcher() -> None:
    ctx = build_kalix_context(
        "orchid", depth_level="researcher", lexicon_loader=_mock_loader([])
    )
    assert ctx["kalix_persona_context"]["depth_level"] == "researcher"


def test_oc_modules_passed_through() -> None:
    modules = ["lexicon", "literature_extraction"]
    ctx = build_kalix_context("orchid", oc_modules=modules, lexicon_loader=_mock_loader([]))
    assert ctx["kalix_persona_context"]["oc_module_awareness"] == modules
    assert ctx["oc_module_awareness"] == modules


def test_empty_oc_modules_is_empty_list() -> None:
    ctx = build_kalix_context("orchid", lexicon_loader=_mock_loader([]))
    assert ctx["oc_module_awareness"] == []


def test_custom_persona_config_is_preserved() -> None:
    config = {"org_id": "fcos", "theme": "dark"}
    ctx = build_kalix_context("orchid", persona_config=config, lexicon_loader=_mock_loader([]))
    assert ctx["kalix_persona_context"]["persona_config"] == config


# ── 4. Governance invariants ──────────────────────────────────────────────────

def test_governance_canonical_graph_mutated_false() -> None:
    ctx = build_kalix_context("orchid", lexicon_loader=_mock_loader([]))
    assert ctx["canonical_graph_mutated"] is False


def test_governance_engineering_dispatch_false() -> None:
    ctx = build_kalix_context("orchid", lexicon_loader=_mock_loader([]))
    assert ctx["engineering_dispatch_authorized"] is False


def test_governance_provider_calls_zero() -> None:
    ctx = build_kalix_context("orchid", lexicon_loader=_mock_loader([]))
    assert ctx["provider_calls"] == 0


# ── 5. Graceful failure ───────────────────────────────────────────────────────

def test_lexicon_failure_does_not_raise() -> None:
    def boom(**_kw: Any) -> list[Any]:
        raise RuntimeError("Lexicon unavailable")

    ctx = build_kalix_context("Dendrobium", lexicon_loader=boom)
    assert ctx["lexicon"]["available"] is False
    assert "kalix_persona_context" in ctx
