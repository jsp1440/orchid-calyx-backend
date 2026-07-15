"""Orchid Continuum scientific Knowledge Graph package.

Canonical scientific objects are graph *nodes*; their biological, evidentiary,
educational and provenance relationships are graph *edges*.  Traversal, quality
metrics and idempotent publication are exposed here.
"""

from .models import Edge, Node
from .publisher import (
    DomainAdapter,
    EdgeSpec,
    NodeSpec,
    PublishResult,
    canonical_key,
    publish_domain,
)
from .quality import quality_report
from .repository import (
    GraphRepository,
    InMemoryGraphRepository,
    PostgresGraphRepository,
)
from .traversal import traverse
from .vocabulary import ALL_DOMAINS, EDGE_TYPE_DOMAIN, NODE_TYPE_DOMAIN

__all__ = [
    "Node", "Edge", "GraphRepository", "InMemoryGraphRepository",
    "PostgresGraphRepository", "traverse", "quality_report", "canonical_key",
    "NodeSpec", "EdgeSpec", "DomainAdapter", "PublishResult", "publish_domain",
    "ALL_DOMAINS", "NODE_TYPE_DOMAIN", "EDGE_TYPE_DOMAIN",
]
