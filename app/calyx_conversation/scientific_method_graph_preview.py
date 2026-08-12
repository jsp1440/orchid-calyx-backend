"""Read-only preview of publication-eligible scientific-method graph structure.

Given canonical literature document ids, this bridge follows the existing source
bindings back to ``PaperKnowledge``, revalidates immutable source integrity,
resolves extracted taxon entities only by exact active Knowledge Graph labels, and
builds the strict publication-eligible graph projection. It never publishes the
returned specs and never mutates review or graph state.
"""

from __future__ import annotations

import os
from typing import Any, Iterable

import psycopg

from app.literature_extraction.repository import LiteratureResultRepository
from app.literature_extraction.source_binding import (
    FileLiteratureSourceBindingRepository,
    LiteratureSourceBindingError,
)
from runtime.knowledge_graph.exact_taxon_resolution import (
    resolve_exact_taxon_keys_with_cursor,
)
from runtime.knowledge_graph.publication_eligible_paper_graph import (
    build_publication_eligible_paper_graph_specs,
)

LITERATURE_SOURCE_OBJECT_TYPE = "LITERATURE_DOCUMENT"
MAX_DOCUMENTS = 8


def _root() -> str:
    return os.getenv("LITERATURE_EXTRACTION_ROOT", "runtime/literature_extraction")


def _document_ids(values: Iterable[int | str], limit: int) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    maximum = max(1, min(int(limit), MAX_DOCUMENTS))
    for raw in values:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value <= 0 or value in seen:
            continue
        seen.add(value)
        result.append(value)
        if len(result) >= maximum:
            break
    return result


def preview_scientific_method_graph_for_documents(
    document_ids: Iterable[int | str],
    *,
    root: str | None = None,
    dsn: str | None = None,
    max_documents: int = MAX_DOCUMENTS,
) -> dict[str, Any]:
    """Return bounded strict graph previews for canonical literature documents."""
    ids = _document_ids(document_ids, max_documents)
    if not ids:
        return {
            "status": "not_requested",
            "read_only": True,
            "knowledge_graph_mutation": False,
            "documents": {},
        }

    resolved_dsn = (dsn or os.getenv("DATABASE_URL") or "").strip()
    if not resolved_dsn:
        return {
            "status": "unavailable",
            "reason": "DATABASE_URL_NOT_CONFIGURED",
            "read_only": True,
            "knowledge_graph_mutation": False,
            "documents": {},
        }

    resolved_root = root or _root()
    papers = LiteratureResultRepository(resolved_root)
    bindings = FileLiteratureSourceBindingRepository(resolved_root)
    documents: dict[str, Any] = {}
    total_nodes = 0
    total_edges = 0

    try:
        with psycopg.connect(resolved_dsn, connect_timeout=5) as conn, conn.cursor() as cur:
            conn.read_only = True
            for document_id in ids:
                matched = bindings.find_by_source_object(
                    LITERATURE_SOURCE_OBJECT_TYPE,
                    document_id,
                    limit=4,
                )
                if not matched:
                    documents[str(document_id)] = {
                        "status": "no_canonical_extraction_binding",
                        "previews": [],
                        "integrity_failures": [],
                    }
                    continue

                previews: list[dict[str, Any]] = []
                failures: list[str] = []
                for binding in matched:
                    paper = papers.get(binding.paper_id)
                    raw_bytes = papers.get_raw_bytes(binding.paper_id)
                    if paper is None or raw_bytes is None:
                        failures.append(
                            f"{binding.paper_id}:EXTRACTION_BUNDLE_INCOMPLETE"
                        )
                        continue
                    try:
                        binding.validate_integrity(paper, raw_bytes)
                    except LiteratureSourceBindingError as exc:
                        failures.append(f"{binding.paper_id}:{exc.code}")
                        continue

                    resolution = resolve_exact_taxon_keys_with_cursor(cur, paper)
                    bundle = build_publication_eligible_paper_graph_specs(
                        paper,
                        taxon_keys_by_entity_id=resolution.keys_by_entity_id,
                    )
                    node_types: dict[str, int] = {}
                    edge_types: dict[str, int] = {}
                    for node in bundle.nodes:
                        node_types[node.node_type] = node_types.get(node.node_type, 0) + 1
                    for edge in bundle.edges:
                        edge_types[edge.edge_type] = edge_types.get(edge.edge_type, 0) + 1
                    preview = {
                        "paper_id": binding.paper_id,
                        "binding_fingerprint": binding.fingerprint,
                        "source_hash": paper.source.content_hash,
                        "title": paper.metadata.title,
                        "exact_taxon_resolutions": resolution.resolved_count,
                        "unresolved_taxon_entity_ids": list(
                            resolution.unresolved_entity_ids
                        ),
                        "ambiguous_taxon_entity_ids": list(
                            resolution.ambiguous_entity_ids
                        ),
                        "node_count": len(bundle.nodes),
                        "edge_count": len(bundle.edges),
                        "node_types": node_types,
                        "edge_types": edge_types,
                        "candidate_or_ineligible_objects_omitted": (
                            bundle.candidate_objects_omitted
                        ),
                        "publication_key": bundle.publication_key,
                        "publication_eligible_claims": sum(
                            node.node_type
                            in {
                                "observation",
                                "result",
                                "hypothesis",
                                "method",
                                "limitation",
                                "recommendation",
                                "assertion",
                            }
                            and node.confidence_label == "publication_eligible"
                            for node in bundle.nodes
                        ),
                    }
                    previews.append(preview)
                    total_nodes += len(bundle.nodes)
                    total_edges += len(bundle.edges)

                status = "available" if previews else "integrity_validation_failed"
                documents[str(document_id)] = {
                    "status": status,
                    "previews": previews,
                    "integrity_failures": failures,
                }
    except psycopg.Error as exc:
        return {
            "status": "unavailable",
            "reason": f"SCIENTIFIC_METHOD_GRAPH_PREVIEW_FAILED:{exc.__class__.__name__}",
            "read_only": True,
            "knowledge_graph_mutation": False,
            "documents": {},
        }

    return {
        "status": "available",
        "contract": "calyx-scientific-method-graph-preview-v2-strict-publication",
        "read_only": True,
        "knowledge_graph_mutation": False,
        "automatic_publication": False,
        "document_count": len(ids),
        "preview_node_count": total_nodes,
        "preview_edge_count": total_edges,
        "documents": documents,
    }
