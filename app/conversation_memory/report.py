from __future__ import annotations

from datetime import datetime
from typing import Any

REPORT_SCHEMA_VERSION = "calyx-conversation-report/v1"


def _text(value: Any, fallback: str = "Not set") -> str:
    normalized = " ".join(str(value or "").strip().split())
    return normalized or fallback


def _timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return _text(value, "Unknown")


def _source_key(source: dict[str, Any]) -> tuple[str, str, str]:
    citation = dict(source.get("citation") or {})
    return (
        _text(source.get("result_id"), ""),
        _text(citation.get("revision_id"), ""),
        _text(citation.get("identifier"), ""),
    )


def build_conversation_markdown(conversation: dict[str, Any]) -> str:
    """Render persisted conversation context without elevating it to evidence."""
    messages = list(conversation.get("messages") or [])
    source_refs: list[dict[str, Any]] = []
    source_index_map: dict[tuple[str, str, str], int] = {}
    seen: set[tuple[str, str, str]] = set()
    for message in messages:
        for source in message.get("source_refs") or []:
            item = dict(source)
            key = _source_key(item)
            if key in seen:
                continue
            seen.add(key)
            source_refs.append(item)
            source_index_map[key] = len(source_refs)

    lines = [
        "# Calyx Research Conversation Report",
        "",
        f"- Report schema: `{REPORT_SCHEMA_VERSION}`",
        f"- Conversation ID: `{_text(conversation.get('conversation_id'))}`",
        f"- Title: {_text(conversation.get('title'), 'Calyx conversation')}",
        f"- Project ID: `{_text(conversation.get('project_id'))}`",
        f"- Created: {_timestamp(conversation.get('created_at'))}",
        f"- Updated: {_timestamp(conversation.get('updated_at'))}",
        f"- Active taxon context: `{_text(conversation.get('active_taxon_id'))}`",
        f"- Active document context: `{_text(conversation.get('active_document_id'))}`",
        "",
        "## Governance and epistemic status",
        "",
        "This export preserves a private research conversation. Conversation text and routing context are **not scientific evidence** and are not canonical Orchid Continuum knowledge.",
        "",
        "- Data status: `CONVERSATION_CONTEXT`",
        "- Evidence authority: `false`",
        "- Scientific publication authorized: `false`",
        "- Knowledge Graph mutation authorized: `false`",
        "- Model-memory evidence authority: `false`",
        "",
        "Each Calyx answer below preserves the epistemic status recorded when that turn was created. Source references are listed separately and remain the authority for any scientific claim.",
        "",
        "## Conversation",
        "",
    ]

    if not messages:
        lines.extend(["_No messages have been recorded in this conversation._", ""])
    else:
        for index, message in enumerate(messages, start=1):
            role = "Calyx" if message.get("role") == "CALYX" else "Researcher"
            lines.extend(
                [
                    f"### {index}. {role}",
                    "",
                    f"- Recorded: {_timestamp(message.get('created_at'))}",
                    f"- Data status: `{_text(message.get('data_status'), 'CONVERSATION_CONTEXT')}`",
                ]
            )
            if message.get("epistemic_status"):
                lines.append(f"- Epistemic status: `{_text(message.get('epistemic_status'))}`")
            context = dict(message.get("context") or {})
            if context:
                lines.extend(
                    [
                        f"- Project context: `{_text(context.get('active_project_id'))}`",
                        f"- Taxon context: `{_text(context.get('active_taxon_id'))}`",
                        f"- Document context: `{_text(context.get('active_document_id'))}`",
                    ]
                )
            msg_source_indices = []
            for source in message.get("source_refs") or []:
                idx = source_index_map.get(_source_key(dict(source)))
                if idx is not None:
                    msg_source_indices.append(idx)
            if msg_source_indices:
                refs_str = ", ".join(f"[Source {i}](#source-{i})" for i in msg_source_indices)
                lines.append(f"- Sources: {refs_str}")
            lines.extend(["", str(message.get("content") or ""), ""])

    lines.extend(["## Source reference ledger", ""])
    if not source_refs:
        lines.extend([
            "_No persisted source references are attached to this conversation. This does not convert conversation text into evidence._",
            "",
        ])
    else:
        for index, source in enumerate(source_refs, start=1):
            citation = dict(source.get("citation") or {})
            lines.extend(
                [
                    f'### <a id="source-{index}"></a>Source {index}: {_text(source.get("title"), source.get("object_type") or "Continuum record")}',
                    "",
                    f"- Result ID: `{_text(source.get('result_id'))}`",
                    f"- Object type: `{_text(source.get('object_type'))}`",
                    f"- Document ID: `{_text(citation.get('document_id'))}`",
                    f"- Document: {_text(citation.get('document_title'))}",
                    f"- Revision: `{_text(citation.get('revision_id'))}`",
                    f"- Identifier: `{_text(citation.get('identifier'))}`",
                    f"- Locator: {_text(citation.get('locator'))}",
                    "",
                ]
            )

    lines.extend([
        "## Interpretation boundary",
        "",
        "This report is a research artifact, not a peer-reviewed scientific conclusion. Exporting it does not publish claims, alter evidence review state, or mutate the Knowledge Graph.",
        "",
    ])
    return "\n".join(lines)
