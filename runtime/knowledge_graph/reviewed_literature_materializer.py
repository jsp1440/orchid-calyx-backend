"""Governed materialization of reviewed literature extraction into ``oc_graph``.

This is the publication-side companion to the read-only scientific-method graph
preview.  It follows canonical literature source bindings, verifies immutable
source integrity, resolves taxa by exact active graph identity, builds the strict
publication-eligible ``PaperKnowledge`` graph projection, and validates all graph
semantics/endpoints before any write is allowed.

Dry-run planning is the default. Production mutation requires an explicit
literature-document list, ``execute=True``, and the exact confirmation token. The
entire requested slice commits once or rolls back as a unit under the canonical
single-writer graph lock.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable

from app.literature_extraction.repository import LiteratureResultRepository
from app.literature_extraction.source_binding import (
    FileLiteratureSourceBindingRepository,
    LiteratureSourceBindingError,
)

from .exact_taxon_resolution import resolve_exact_taxon_keys_for_paper
from .paper_knowledge_graph import PaperGraphBundle
from .publication_eligible_paper_graph import (
    build_publication_eligible_paper_graph_specs,
)
from .publisher import DomainAdapter, publish_domain
from .repository import PostgresGraphRepository, WritablePostgresGraphRepository
from .vocabulary import EDGE_TYPE_DOMAIN, NODE_TYPE_DOMAIN

CONFIRMATION_TOKEN = "PUBLISH_REVIEWED_LITERATURE_GRAPH"
LITERATURE_SOURCE_OBJECT_TYPE = "LITERATURE_DOCUMENT"
DEFAULT_MAX_DOCUMENTS = 8
MAX_DOCUMENTS = 50


@dataclass(frozen=True, slots=True)
class PreparedLiteratureGraph:
    document_id: int
    paper_id: str
    binding_fingerprint: str
    source_hash: str
    bundle: PaperGraphBundle
    exact_taxon_resolutions: int
    unresolved_taxon_entity_ids: tuple[str, ...]
    ambiguous_taxon_entity_ids: tuple[str, ...]


def _root(root: str | None) -> str:
    return root or os.getenv(
        "LITERATURE_EXTRACTION_ROOT", "runtime/literature_extraction"
    )


def _document_ids(values: Iterable[int | str] | None, limit: int) -> tuple[int, ...]:
    if values is None:
        return ()
    maximum = max(1, min(int(limit), MAX_DOCUMENTS))
    result: list[int] = []
    seen: set[int] = set()
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
    return tuple(result)


def _bundle_validation(
    graph: PostgresGraphRepository,
    bundle: PaperGraphBundle,
) -> list[str]:
    invalid: list[str] = []
    local_keys = {node.key() for node in bundle.nodes}
    for node in bundle.nodes:
        if node.node_type not in NODE_TYPE_DOMAIN:
            invalid.append(f"node_type:{node.node_type}")
    checked_external: dict[str, bool] = {}
    for edge in bundle.edges:
        if edge.edge_type not in EDGE_TYPE_DOMAIN:
            invalid.append(f"edge_type:{edge.edge_type}")
        for endpoint in (edge.from_key, edge.to_key):
            if endpoint in local_keys:
                continue
            exists = checked_external.get(endpoint)
            if exists is None:
                exists = graph.get_node_by_key(endpoint) is not None
                checked_external[endpoint] = exists
            if not exists:
                invalid.append(f"edge_missing_endpoint:{edge.edge_type}:{endpoint}")
    return list(dict.fromkeys(invalid))


def _prepare(
    dsn: str,
    document_ids: tuple[int, ...],
    *,
    root: str,
) -> tuple[list[PreparedLiteratureGraph], dict[str, Any]]:
    papers = LiteratureResultRepository(root)
    bindings = FileLiteratureSourceBindingRepository(root)
    graph = PostgresGraphRepository(dsn)
    prepared: list[PreparedLiteratureGraph] = []
    documents: dict[str, Any] = {}

    for document_id in document_ids:
        matched = bindings.find_by_source_object(
            LITERATURE_SOURCE_OBJECT_TYPE,
            document_id,
            limit=4,
        )
        if not matched:
            documents[str(document_id)] = {
                "status": "no_canonical_extraction_binding",
                "valid": False,
            }
            continue
        if len(matched) != 1:
            documents[str(document_id)] = {
                "status": "ambiguous_canonical_extraction_bindings",
                "valid": False,
                "binding_count": len(matched),
                "paper_ids": [binding.paper_id for binding in matched],
            }
            continue

        binding = matched[0]
        paper = papers.get(binding.paper_id)
        raw_bytes = papers.get_raw_bytes(binding.paper_id)
        if paper is None or raw_bytes is None:
            documents[str(document_id)] = {
                "status": "extraction_bundle_incomplete",
                "valid": False,
                "paper_id": binding.paper_id,
            }
            continue
        try:
            binding.validate_integrity(paper, raw_bytes)
        except LiteratureSourceBindingError as exc:
            documents[str(document_id)] = {
                "status": "source_integrity_failed",
                "valid": False,
                "paper_id": binding.paper_id,
                "error": exc.code,
            }
            continue

        resolution = resolve_exact_taxon_keys_for_paper(dsn, paper)
        bundle = build_publication_eligible_paper_graph_specs(
            paper,
            taxon_keys_by_entity_id=resolution.keys_by_entity_id,
        )
        invalid = _bundle_validation(graph, bundle)
        eligible_claims = sum(
            node.confidence_label == "publication_eligible"
            and node.node_type
            in {
                "observation",
                "result",
                "hypothesis",
                "method",
                "limitation",
                "recommendation",
                "assertion",
            }
            for node in bundle.nodes
        )
        status = "ready" if not invalid else "invalid_graph_projection"
        documents[str(document_id)] = {
            "status": status,
            "valid": not invalid,
            "paper_id": binding.paper_id,
            "binding_fingerprint": binding.fingerprint,
            "source_hash": paper.source.content_hash,
            "node_count": len(bundle.nodes),
            "edge_count": len(bundle.edges),
            "publication_eligible_claims": eligible_claims,
            "candidate_or_ineligible_objects_omitted": (
                bundle.candidate_objects_omitted
            ),
            "exact_taxon_resolutions": resolution.resolved_count,
            "unresolved_taxon_entity_ids": list(
                resolution.unresolved_entity_ids
            ),
            "ambiguous_taxon_entity_ids": list(
                resolution.ambiguous_entity_ids
            ),
            "invalid": invalid,
        }
        if invalid:
            continue
        prepared.append(
            PreparedLiteratureGraph(
                document_id=document_id,
                paper_id=binding.paper_id,
                binding_fingerprint=binding.fingerprint,
                source_hash=paper.source.content_hash,
                bundle=bundle,
                exact_taxon_resolutions=resolution.resolved_count,
                unresolved_taxon_entity_ids=resolution.unresolved_entity_ids,
                ambiguous_taxon_entity_ids=resolution.ambiguous_entity_ids,
            )
        )

    report = {
        "contract": "calyx-reviewed-literature-graph-materialization-v1",
        "requested_document_ids": list(document_ids),
        "ready_document_ids": [item.document_id for item in prepared],
        "documents": documents,
        "valid": len(prepared) == len(document_ids) and bool(document_ids),
        "production_graph_mutation": False,
        "confirmation_required": CONFIRMATION_TOKEN,
    }
    return prepared, report


def materialize_reviewed_literature_graph(
    dsn: str,
    *,
    document_ids: Iterable[int | str] | None,
    root: str | None = None,
    execute: bool = False,
    confirmation: str | None = None,
    max_documents: int = DEFAULT_MAX_DOCUMENTS,
) -> dict[str, Any]:
    """Plan or transactionally publish reviewed literature graph structure."""
    if not str(dsn or "").strip():
        raise ValueError("DATABASE_URL_REQUIRED")
    ids = _document_ids(document_ids, max_documents)
    if not ids:
        raise ValueError("EXPLICIT_LITERATURE_DOCUMENT_IDS_REQUIRED")
    if execute and confirmation != CONFIRMATION_TOKEN:
        raise PermissionError("REVIEWED_LITERATURE_PUBLICATION_CONFIRMATION_REQUIRED")

    prepared, report = _prepare(dsn, ids, root=_root(root))
    if not execute:
        report["mode"] = "dry_run"
        report["bounded_validation"] = True
        return report
    if not report["valid"]:
        raise ValueError("REVIEWED_LITERATURE_PUBLICATION_PLAN_INVALID")

    repo = WritablePostgresGraphRepository(dsn)
    publication_results: list[dict[str, Any]] = []
    try:
        repo.acquire_publication_lock()
        for item in prepared:
            adapter = DomainAdapter(
                domain="scientific_method",
                source_table="literature_extraction.paper_knowledge",
                produce=lambda rows, bundle=item.bundle: (
                    list(bundle.nodes),
                    list(bundle.edges),
                ),
            )
            result = publish_domain(
                repo,
                adapter,
                [{"document_id": item.document_id, "paper_id": item.paper_id}],
            )
            publication_results.append(
                {
                    "document_id": item.document_id,
                    "paper_id": item.paper_id,
                    "nodes_written": result.nodes_written,
                    "edges_written": result.edges_written,
                    "skipped_existing_nodes": result.skipped_existing_nodes,
                    "skipped_existing_edges": result.skipped_existing_edges,
                    "invalid": list(result.invalid),
                }
            )
            if result.invalid:
                raise RuntimeError(
                    f"LITERATURE_GRAPH_PUBLICATION_INVALID:{item.document_id}"
                )
        repo.commit()
        report["production_graph_mutation"] = True
        report["committed"] = True
        report["mode"] = "publish"
        report["publication_results"] = publication_results
        return report
    except Exception:
        repo.rollback()
        raise
    finally:
        repo.close()
