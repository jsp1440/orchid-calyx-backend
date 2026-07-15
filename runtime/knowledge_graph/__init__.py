"""Orchid Continuum scientific Knowledge Graph package.

Canonical scientific objects are graph *nodes*; their biological, evidentiary,
educational and provenance relationships are graph *edges*.  Traversal, quality
metrics, validation, idempotent publication and a unified build orchestrator are
exposed here.
"""

from .adapters import DOMAIN_ADAPTERS, adapters_by_domain
from .canonical_taxonomy import (
    ACTIVATED_DOMAINS,
    AUTHORITY_SOURCES,
    CANONICAL_AUTHORITY,
    CANONICAL_AUTHORITY_LABEL,
    WITHHELD_DOMAINS,
    AuthorityMapping,
    CanonicalRegistry,
    CanonicalTaxon,
    WorldPlantsRelease,
    build_canonical_registry,
    classify_crosswalk,
    classify_mapping,
    detect_conflicts,
    select_canonical_release,
)
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
from .reporting import (
    domain_coverage_report,
    graph_completeness_report,
    review_queues,
)
from .repository import (
    GraphRepository,
    InMemoryGraphRepository,
    PostgresGraphRepository,
    PublicationLockError,
    WritablePostgresGraphRepository,
)
from .source_registry import (
    SOURCE_QUERIES,
    SourceQuery,
    UnsafeSQLError,
    assert_safe_sql,
    blocked_domains,
    enabled_queries,
    registry_by_domain,
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
    "PostgresGraphRepository", "WritablePostgresGraphRepository", "PublicationLockError",
    "traverse", "quality_report", "canonical_key",
    "NodeSpec", "EdgeSpec", "DomainAdapter", "PublishResult", "publish_domain",
    "ALL_DOMAINS", "NODE_TYPE_DOMAIN", "EDGE_TYPE_DOMAIN",
    "DOMAIN_ADAPTERS", "adapters_by_domain",
    "SourceProvider", "InMemorySourceProvider", "PostgresSourceProvider",
    "SourceQuery", "SOURCE_QUERIES", "registry_by_domain", "enabled_queries",
    "blocked_domains", "assert_safe_sql", "UnsafeSQLError",
    "Checkpoint", "InMemoryCheckpointStore", "JsonFileCheckpointStore",
    "BuildOrchestrator", "ExecutionMode", "DomainOutcome", "validate_graph",
    "CANONICAL_AUTHORITY", "CANONICAL_AUTHORITY_LABEL", "AUTHORITY_SOURCES",
    "ACTIVATED_DOMAINS", "WITHHELD_DOMAINS", "WorldPlantsRelease",
    "AuthorityMapping", "CanonicalTaxon", "CanonicalRegistry",
    "build_canonical_registry", "select_canonical_release",
    "classify_mapping", "classify_crosswalk", "detect_conflicts",
    "domain_coverage_report", "graph_completeness_report", "review_queues",
]
