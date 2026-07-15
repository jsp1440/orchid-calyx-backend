"""Orchid Continuum scientific Knowledge Graph package.

Canonical scientific objects are graph *nodes*; their biological, evidentiary,
educational and provenance relationships are graph *edges*.  Traversal, quality
metrics, validation, idempotent publication and a unified build orchestrator are
exposed here.
"""

from .adapters import DOMAIN_ADAPTERS, adapters_by_domain
from .checkpoint import (
    Checkpoint,
    InMemoryCheckpointStore,
    JsonFileCheckpointStore,
)
from .models import Edge, Node
from .orchestrator import (
    BuildOrchestrator,
    DomainOutcome,
    ExecutionMode,
)
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
from .sources import (
    InMemorySourceProvider,
    PostgresSourceProvider,
    SourceProvider,
)
from .traversal import traverse
from .validation import validate_graph
from .vocabulary import ALL_DOMAINS, EDGE_TYPE_DOMAIN, NODE_TYPE_DOMAIN

__all__ = [
    "Node", "Edge", "GraphRepository", "InMemoryGraphRepository",
    "PostgresGraphRepository", "traverse", "quality_report", "canonical_key",
    "NodeSpec", "EdgeSpec", "DomainAdapter", "PublishResult", "publish_domain",
    "ALL_DOMAINS", "NODE_TYPE_DOMAIN", "EDGE_TYPE_DOMAIN",
    "DOMAIN_ADAPTERS", "adapters_by_domain",
    "SourceProvider", "InMemorySourceProvider", "PostgresSourceProvider",
    "Checkpoint", "InMemoryCheckpointStore", "JsonFileCheckpointStore",
    "BuildOrchestrator", "ExecutionMode", "DomainOutcome", "validate_graph",
]
