"""Kalix context bridge — persona-enriched knowledge grounding.

Delegates ALL Lexicon + Literature retrieval to build_knowledge_context
(KALIX-CONTEXT-001 / PR #1447). This module never re-implements retrieval;
it only adds the Kalix persona layer on top.

Governance
----------
- canonical_graph_mutated: False throughout
- engineering_dispatch_authorized: False
- provider_calls: 0
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

_KALIX_CONTEXT_VERSION = "KALIX-PERSONA-001"


def build_kalix_context(
    query: str,
    *,
    persona_config: dict[str, Any] | None = None,
    depth_level: str = "grower",
    oc_modules: list[str] | None = None,
    lexicon_loader: Callable[..., list[dict[str, Any]]] | None = None,
    literature_repository: Any = None,
) -> dict[str, Any]:
    """Return Kalix persona-enriched knowledge context for *query*.

    Delegates Lexicon + Literature retrieval to
    ``app.calyx_conversation.knowledge_context.build_knowledge_context``.
    The returned dict is safe to include in any governed_context.
    """
    from app.calyx_conversation.knowledge_context import build_knowledge_context

    knowledge = build_knowledge_context(
        query,
        lexicon_loader=lexicon_loader,
        literature_repository=literature_repository,
    )

    modules = list(oc_modules or [])
    return {
        **knowledge,
        "kalix_persona_context": {
            "persona_version": _KALIX_CONTEXT_VERSION,
            "depth_level": depth_level,
            "persona_config": persona_config or {},
            "oc_module_awareness": modules,
        },
        "oc_module_awareness": modules,
        "canonical_graph_mutated": False,
        "engineering_dispatch_authorized": False,
        "provider_calls": 0,
    }
