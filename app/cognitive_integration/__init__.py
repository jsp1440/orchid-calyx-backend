"""Cognitive Integration: execute one scientific question end to end.

The traversal reuses ``app.brain.reasoning_map`` over the existing knowledge
graph. Nothing here is a second graph, a second scheduler, or a second
reasoning engine.
"""

from .executor import CognitiveIntegrationError, execute

__all__ = ["CognitiveIntegrationError", "execute"]
