from __future__ import annotations

import re
from typing import Any

from .routes import BrainQueryRequest, GraphContextRequest, run_brain_query, run_graph_context

# Conservative stop-list for sentence-initial/common capitalized words that are not botanical genera.
_NON_GENUS_TOKENS = {
    "Address",
    "Available",
    "Calyx",
    "Central",
    "Compare",
    "Consider",
    "Current",
    "Distinguish",
    "El",
    "Evaluate",
    "How",
    "Mediterranean",
    "NOAA",
    "Orchid",
    "Orchids",
    "Please",
    "Scientific",
    "The",
    "What",
    "When",
    "Where",
    "Which",
    "Winter",
}


def candidate_genera(message: str, *, limit: int = 16) -> list[str]:
    """Return unique genus-like capitalized tokens, preserving message order.

    Resolution against the canonical Knowledge Graph is the authority; this function is
    intentionally only a cheap candidate extractor so Speak-with-Calyx can discover
    taxa without requiring the browser to author graph_context payloads.
    """

    tokens = re.findall(r"\b[A-Z][a-z]{2,24}\b", message)
    output: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in _NON_GENUS_TOKENS or token in seen:
            continue
        seen.add(token)
        output.append(token)
        if len(output) >= limit:
            break
    return output


def build_continuum_context(message: str, *, max_genera: int = 12) -> dict[str, Any]:
    """Resolve taxa mentioned in a Calyx turn and attach read-only Continuum context.

    Failure of one source never blocks the turn. The returned object is safe to place
    directly in governed_context: it contains only canonical graph/Brain reads plus
    explicit diagnostics. No mutation or publication occurs here.
    """

    candidates = candidate_genera(message, limit=max_genera * 2)
    resolved: list[dict[str, Any]] = []
    diagnostics: list[dict[str, str]] = []

    for genus in candidates:
        if len(resolved) >= max_genera:
            break
        try:
            graph = run_graph_context(
                GraphContextRequest(genus=genus, depth=1, limit=40)
            )
        except Exception as exc:  # source degradation must not fail conversation
            diagnostics.append(
                {"source": "knowledge_graph", "query": genus, "error": str(exc)}
            )
            # Database configuration failure will repeat for every candidate; stop early.
            if "not configured" in str(exc).casefold():
                break
            continue

        if not graph.get("found"):
            continue

        brain: dict[str, Any] | None = None
        try:
            brain = run_brain_query(BrainQueryRequest(text=genus, limit=40))
        except Exception as exc:  # graph context is still useful if Brain query degrades
            diagnostics.append(
                {"source": "brain_graph", "query": genus, "error": str(exc)}
            )

        resolved.append(
            {
                "genus": genus,
                "knowledge_graph": graph,
                "brain_graph": brain,
            }
        )

    return {
        "candidate_genera": candidates,
        "resolved_genera": [item["genus"] for item in resolved],
        "taxa": resolved,
        "diagnostics": diagnostics,
        "read_only": True,
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
    }
