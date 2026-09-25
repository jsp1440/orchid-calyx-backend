from __future__ import annotations

import json

from app.calyx_conversation.evidence_synthesis import SYNTHESIS_CONTRACT_VERSION
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

    # Since CALYX-EVIDENCE-SYNTHESIS-002 the model never receives raw source
    # blocks: every source family is adapted into one synthesis packet and the
    # raw ``retrieval`` payload stays server-side.
    assert "retrieval" not in compact
    packet = compact["synthesis_packet"]
    assert packet["contract_version"] == SYNTHESIS_CONTRACT_VERSION
    items = packet["evidence_items"]
    literature = [
        item
        for item in items
        if isinstance(item, dict) and item.get("source_family") == "external_literature"
    ]
    assert literature
    assert all(item["status"] == "review_required" for item in literature)
    assert all(len(item["statement"]) < 10000 for item in literature)
    assert items[-1]["_additional_items_omitted"] > 0
    assert len(items) <= 17
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
    assert text.startswith("Governed Calyx semantic synthesis context for this turn:\n")
    assert "additional governed context omitted" not in text


def test_model_context_text_truncates_when_compaction_alone_exceeds_budget():
    provider = object.__new__(OpenAIRuntimeResponsesProvider)
    # epistemic_policy is forwarded verbatim (after per-value compaction), so 32
    # long rules exceed the hard model budget even after compaction.
    governed = {
        "epistemic_policy": {f"rule_{index}": "z" * 3000 for index in range(32)}
    }
    text = provider._governed_context_text(governed)
    assert len(text) <= _MAX_CONTEXT_CHARS + 200
    assert text.startswith("Governed Calyx semantic synthesis context for this turn:\n")
    assert text.endswith(
        "\n[additional governed context omitted; full provenance remains server-side]"
    )
