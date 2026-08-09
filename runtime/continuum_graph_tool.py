"""Governed read-only Knowledge Graph tool for Calyx conversation."""

from __future__ import annotations

import os
from typing import Any, Protocol

import psycopg

from runtime.knowledge_graph import (
    GraphRepository,
    PostgresGraphRepository,
    canonical_key,
    traverse,
)

GRAPH_TOOL_SCHEMA_VERSION = "calyx-knowledge-graph-read/v1"


class KnowledgeGraphReadProtocol(Protocol):
    def lookup_taxon(
        self,
        taxon_id: str,
        *,
        depth: int = 1,
        limit: int = 50,
    ) -> dict[str, Any]: ...


class ReadOnlyKnowledgeGraphTool:
    """Resolve and traverse a taxon through read-only Knowledge Graph methods only."""

    def __init__(
        self,
        repository: GraphRepository | None = None,
        *,
        dsn: str | None = None,
    ) -> None:
        self._repository = repository
        self._dsn = dsn

    def _repo(self) -> GraphRepository | None:
        if self._repository is not None:
            return self._repository
        dsn = self._dsn or os.getenv("DATABASE_URL")
        if not dsn:
            return None
        return PostgresGraphRepository(dsn)

    def lookup_taxon(
        self,
        taxon_id: str,
        *,
        depth: int = 1,
        limit: int = 50,
    ) -> dict[str, Any]:
        normalized = " ".join(str(taxon_id or "").strip().split())
        if not normalized:
            raise ValueError("GRAPH_TAXON_ID_REQUIRED")
        if not 1 <= int(depth) <= 2:
            raise ValueError("GRAPH_DEPTH_INVALID")
        if not 1 <= int(limit) <= 100:
            raise ValueError("GRAPH_LIMIT_INVALID")

        repo = self._repo()
        if repo is None:
            return self._status(
                "unavailable",
                taxon_id=normalized,
                reason="DATABASE_URL_NOT_CONFIGURED",
            )

        key = normalized if ":" in normalized else canonical_key("taxon", normalized)
        try:
            focal = repo.get_node_by_key(key)
            if focal is None:
                return self._status(
                    "not_found",
                    taxon_id=normalized,
                    canonical_key=key,
                    reason="TAXON_NOT_FOUND_IN_GRAPH",
                )
            traversal = traverse(repo, focal, depth=int(depth), limit=int(limit), offset=0)
        except psycopg.Error as exc:
            return self._status(
                "unavailable",
                taxon_id=normalized,
                canonical_key=key,
                reason=f"GRAPH_READ_FAILED:{exc.__class__.__name__}",
            )

        return {
            "schema_version": GRAPH_TOOL_SCHEMA_VERSION,
            "status": "found",
            "read_only": True,
            "knowledge_graph_mutation_authorized": False,
            "taxon_id": normalized,
            "canonical_key": key,
            "focal_node": traversal.get("focal_node"),
            "nodes": list(traversal.get("nodes") or []),
            "edges": list(traversal.get("edges") or []),
            "node_types": list(traversal.get("node_types") or []),
            "edge_types": list(traversal.get("edge_types") or []),
            "domain_coverage": dict(traversal.get("domain_coverage") or {}),
            "data_gaps": list(traversal.get("data_gaps") or []),
            "graph": dict(traversal.get("graph") or {}),
            "pagination": dict(traversal.get("pagination") or {}),
        }

    @staticmethod
    def _status(
        status: str,
        *,
        taxon_id: str,
        reason: str,
        canonical_key: str | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": GRAPH_TOOL_SCHEMA_VERSION,
            "status": status,
            "read_only": True,
            "knowledge_graph_mutation_authorized": False,
            "taxon_id": taxon_id,
            "canonical_key": canonical_key,
            "reason": reason,
            "focal_node": None,
            "nodes": [],
            "edges": [],
            "node_types": [],
            "edge_types": [],
            "domain_coverage": {},
            "data_gaps": [],
            "graph": {"depth": 0, "node_count": 0, "edge_count": 0},
            "pagination": {
                "limit": 0,
                "offset": 0,
                "truncated": False,
                "next_offset": None,
            },
        }
