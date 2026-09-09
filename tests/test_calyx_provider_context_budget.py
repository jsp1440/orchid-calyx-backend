from __future__ import annotations

import json

from app.calyx_conversation.provider_runtime import (
    _MAX_CONTEXT_CHARS,
    _MAX_HISTORY_CHARS,
    OpenAIRuntimeResponsesProvider,
    _compact_messages,
    compact_governed_context,
)


def test_compact_messages_bounds_long_conversation_history():
    messages = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": "x" * 5000}
        for index in range(12)
    ]
    compact = _compact_messages(messages)
    assert sum(len(item["content"]) for item in compact) <= _MAX_HISTORY_CHARS
    assert compact[-1]["role"] == messages[-1]["role"]


def test_governed_context_compacts_large_retrieval_objects():
    governed = {
        "retrieval": {
            "external_literature": {
                "results": [
                    {"title": f"paper-{index}", "abstract": "a" * 10000}
                    for index in range(20)
                ]
            }
        },
        "mission": {"supporting_evidence": [{"text": "e" * 10000}] * 20},
        "epistemic_policy": {"external_literature_requires_review": True},
    }
    compact = compact_governed_context(governed)
    packet = compact["synthesis_packet"]
    assert packet["contract_version"] == "CALYX-EVIDENCE-SYNTHESIS-002"
    evidence_items = packet["evidence_items"]
    assert any(
        item.get("source_family") == "external_literature"
        for item in evidence_items
        if isinstance(item, dict)
    )
    assert evidence_items[-1]["_additional_items_omitted"] > 0
    assert len(evidence_items) <= 17
    assert compact["epistemic_policy"]["external_literature_requires_review"] is True

    assert len(json.dumps(compact, default=str)) <= _MAX_CONTEXT_CHARS


def test_model_context_text_has_hard_character_budget():
    provider = object.__new__(OpenAIRuntimeResponsesProvider)
    governed = {
        "retrieval": {"results": [{"text": "x" * 10000}] * 100},
        "mission": {"sources": [{"text": "y" * 10000}] * 100},
    }
    text = provider._governed_context_text(governed)
    assert len(text) <= _MAX_CONTEXT_CHARS + 200
    assert "Governed Calyx semantic synthesis context for this turn:" in text


def test_the_character_budget_actually_truncates_when_it_is_reached(monkeypatch):
    """Covers the backstop the test above cannot reach.

    _MAX_CONTEXT_CHARS is unreachable through real input. compact_governed_context
    runs everything through provider_context, which emits only the canonical key
    set, and _compact_value caps strings at 2200, dicts at 32 keys and lists at 16
    items. Every payload shape I could construct - thirty source families of
    maximal records, a deep mission with continuum and climate - lands between 2KB
    and 15KB against a 60KB limit.

    So the previous version of the assertion above passed whether or not the
    truncation existed: deleting the `if len(text) > _MAX_CONTEXT_CHARS` branch
    left it green. The budget is real defence-in-depth and worth keeping, but it
    has to be tested where it can actually engage. The collaborator is replaced,
    not the code under test - the truncation in _governed_context_text is what
    runs here.
    """
    provider = object.__new__(OpenAIRuntimeResponsesProvider)
    oversized = {"evidence": "z" * (_MAX_CONTEXT_CHARS * 2)}
    monkeypatch.setattr(
        "app.calyx_conversation.provider_runtime.compact_governed_context",
        lambda governed_context, **_: oversized,
    )

    text = provider._governed_context_text({"anything": True})

    assert len(text) <= _MAX_CONTEXT_CHARS + 200
    assert "additional governed context omitted" in text
    assert "full provenance remains server-side" in text
