"""Graph-grounded scientific reasoning pilot (read-only, provider-free).

See ``docs/architecture/GRAPH-GROUNDED-REASONING-PILOT.md``.
"""

from .contracts import CONTRACT_VERSION, Facet, ResultState, ScientificQuestion
from .pipeline import GraphGroundedReasoner

__all__ = [
    "CONTRACT_VERSION",
    "Facet",
    "GraphGroundedReasoner",
    "ResultState",
    "ScientificQuestion",
]
