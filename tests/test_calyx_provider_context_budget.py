from __future__ import annotations

import json
from typing import Any

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

    # Raw retrieval is deliberately no longer forwarded. compact_governed_context
    # now adapts every source family into the canonical evidence contract and
    # hands the model a synthesis packet instead, so asserting the old
    # compact["retrieval"]["external_literature"]["results"] path was asserting a
    # shape the code had stopped producing on purpose. Pinning its absence keeps
    # unadapted payloads from being re-added by accident.
    assert "retrieval" not in compact
    assert "synthesis_packet" in compact

    # The property that actually matters: oversized collections are still
    # truncated, and the truncation is declared rather than silent.
    markers = _find_key(compact, "_additional_items_omitted")
    assert markers, "large collections must still be truncated with an explicit marker"
    assert all(isinstance(count, int) and count > 0 for count in markers)

    # Epistemic labels survive compaction unchanged - the one thing that must
    # never be summarized away.
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
    # Matched loosely on purpose. The header gained "semantic synthesis" when the
    # packet was introduced; what this test is for is the budget and the fact
    # that the block is labelled as governed context, not the exact wording.
    assert text.startswith("Governed Calyx")
    assert "context for this turn:" in text


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


def _find_key(value: Any, key: str) -> list[Any]:
    """Collect every value stored under `key`, at any depth.

    The compactor is free to move where it truncates; it is not free to stop
    declaring that it truncated. Searching by key rather than by path keeps this
    test measuring the guarantee instead of the layout.
    """
    found: list[Any] = []
    if isinstance(value, dict):
        for name, item in value.items():
            if name == key:
                found.append(item)
            found.extend(_find_key(item, key))
    elif isinstance(value, list):
        for item in value:
            found.extend(_find_key(item, key))
    return found
