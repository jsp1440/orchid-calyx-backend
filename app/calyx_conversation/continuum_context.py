from __future__ import annotations

import re
from typing import Any

from .routes import (
    BrainQueryRequest,
    GraphContextRequest,
    run_brain_query,
    run_graph_context,
)
from .semantic_context import build_semantic_context

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
_ENVIRONMENT_TERMS = (
    "rain",
    "precip",
    "climate",
    "temperature",
    "temp_",
    "humidity",
    "elevation",
    "altitude",
    "bioclim",
    "seasonality",
    "moisture",
)


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


def _environmental_facts(graph: dict[str, Any], *, limit: int = 20) -> list[dict[str, Any]]:
    """Extract already-canonical environmental fields from graph nodes/edges.

    This does not calculate a climate envelope or call an external weather service. It
    only makes climate-related facts already present in canonical graph records visible
    to the conversational provider with their graph location.
    """

    facts: list[dict[str, Any]] = []
    for collection_name in ("nodes", "edges"):
        for item in graph.get(collection_name) or []:
            if not isinstance(item, dict):
                continue
            mappings: list[tuple[str, dict[str, Any]]] = [("record", item)]
            properties = item.get("properties")
            if isinstance(properties, dict):
                mappings.append(("properties", properties))
            for location, mapping in mappings:
                for key, value in mapping.items():
                    key_text = str(key).casefold()
                    if not any(term in key_text for term in _ENVIRONMENT_TERMS):
                        continue
                    if isinstance(value, (dict, list, tuple, set)):
                        value = str(value)[:500]
                    facts.append(
                        {
                            "collection": collection_name,
                            "location": location,
                            "key": str(key),
                            "value": value,
                            "canonical_key": item.get("canonical_key"),
                            "edge_type": item.get("edge_type"),
                        }
                    )
                    if len(facts) >= limit:
                        return facts
    return facts


def build_continuum_context(message: str, *, max_genera: int = 12) -> dict[str, Any]:
    """Attach read-only graph, Brain, environment, and semantic concept context.

    Failure of one source never blocks the turn. The returned object is safe to place
    directly in governed_context. Approved Lexicon concepts are a semantic projection
    only; this function never creates, promotes, revises, publishes, or mutates them.
    """

    semantic = build_semantic_context(message)
    candidates = candidate_genera(message, limit=max_genera * 2)
    resolved: list[dict[str, Any]] = []
    diagnostics: list[dict[str, str]] = []
    for diagnostic in semantic.get("diagnostics") or []:
        if isinstance(diagnostic, dict):
            diagnostics.append(
                {
                    "source": str(diagnostic.get("source") or "semantic_context"),
                    "query": message[:120],
                    "error": str(diagnostic.get("error") or "unavailable"),
                }
            )

    for genus in candidates:
        if len(resolved) >= max_genera:
            break
        try:
            graph = run_graph_context(
                GraphContextRequest(genus=genus, depth=1, limit=40)
            )
        except (RuntimeError, TypeError, ValueError) as exc:
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
        except (RuntimeError, TypeError, ValueError) as exc:
            diagnostics.append(
                {"source": "brain_graph", "query": genus, "error": str(exc)}
            )

        resolved.append(
            {
                "genus": genus,
                "knowledge_graph": graph,
                "brain_graph": brain,
                "environmental_facts": _environmental_facts(graph),
            }
        )

    return {
        "candidate_genera": candidates,
        "resolved_genera": [item["genus"] for item in resolved],
        "taxa": resolved,
        "semantic_context": semantic,
        "semantic_links": semantic.get("links") or [],
        "diagnostics": diagnostics,
        "read_only": True,
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
    }
