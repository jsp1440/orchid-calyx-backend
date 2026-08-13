from __future__ import annotations

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
    records = compact["retrieval"]["external_literature"]["results"]
    assert len(records) == 9
    assert records[-1]["_additional_items_omitted"] == 12
    assert compact["epistemic_policy"]["external_literature_requires_review"] is True


def test_model_context_text_has_hard_character_budget():
    provider = object.__new__(OpenAIRuntimeResponsesProvider)
    governed = {
        "retrieval": {"results": [{"text": "x" * 10000}] * 100},
        "mission": {"sources": [{"text": "y" * 10000}] * 100},
    }
    text = provider._governed_context_text(governed)
    assert len(text) <= _MAX_CONTEXT_CHARS + 200
    assert "Governed Calyx context for this turn:" in text
