"""Bounded, read-only graph retrieval and exact-document literature anchoring."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Protocol

from app.evidence_retrieval.models import RetrievalQuery
from runtime.knowledge_graph.canonical_taxonomy import canonical_name_of
from runtime.knowledge_graph.causal_vocabulary import causal_relation_semantics
from runtime.knowledge_graph.claim_provenance import parse_claim_provenance
from runtime.knowledge_graph.models import Edge, Node
from runtime.knowledge_graph.vocabulary import EDGE_TYPE_DOMAIN, domain_for_edge_type

from .contracts import (
    CONTRACT_VERSION,
    FACET_DOMAINS,
    MAX_EVIDENCE_RECORDS,
    MAX_GRAPH_RECORDS,
    PAYLOAD_ALLOWLIST,
    AnchorState,
    EvidenceItem,
    EvidencePacket,
    ResolutionState,
    ScientificQuestion,
    TaxonResolution,
)


class ReadableGraph(Protocol):
    def get_node_by_key(self, canonical_key: str) -> Node | None: ...
    def get_nodes(self, node_ids: Iterable[int]) -> list[Node]: ...
    def get_outgoing_edges(
        self,
        node_ids: Iterable[int],
        edge_types: Iterable[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Edge]: ...


class ReadOnlyGraphView:
    """Expose only the three read methods the pilot needs.

    Wrapping the repository means no write method (``upsert_*``, ``commit``,
    publication locks) is reachable from this package even when the caller
    hands in a writable repository.
    """

    __slots__ = ("_repo",)

    def __init__(self, repo: ReadableGraph):
        self._repo = repo

    def get_node_by_key(self, canonical_key: str) -> Node | None:
        return self._repo.get_node_by_key(canonical_key)

    def get_nodes(self, node_ids: Iterable[int]) -> list[Node]:
        return self._repo.get_nodes(node_ids)

    def get_outgoing_edges(self, node_ids, edge_types=None, limit=100, offset=0):
        return self._repo.get_outgoing_edges(
            node_ids, edge_types=edge_types, limit=limit, offset=offset
        )


SearchFn = Callable[[RetrievalQuery], dict[str, Any]]


def _polarity(edge_type: str) -> int:
    semantics = causal_relation_semantics(edge_type)
    return int(semantics["polarity"]) if semantics else 1


def _withheld(edge: Edge, node: Node | None) -> bool:
    for payload in (edge.payload or {}, (node.payload if node else None) or {}):
        if payload.get("sensitive_locality") or payload.get("display_policy") == "WITHHELD":
            return True
    return False


def _anchor(search: SearchFn | None, document_id: str | None, accepted_name: str):
    """Resolve a declared source document to an exact citation via the index."""

    if not document_id:
        return AnchorState.SOURCE_UNDECLARED, None
    if search is None:
        return AnchorState.ANCHOR_UNAVAILABLE, None
    result = search(
        RetrievalQuery(
            text=accepted_name,
            mode="HYBRID",
            limit=1,
            per_source_limit=1,
            parent_expansion="NONE",
            filters={"document_id": document_id},
        )
    )
    for row in result.get("results", []):
        citation = row.get("citation") or {}
        if citation.get("document_id") != document_id:
            continue
        locator = citation.get("locator")
        content_hash = row.get("source_content_hash")
        if (
            citation.get("revision_id") is not None
            and citation.get("source_anchor_ids")
            and isinstance(locator, dict)
            and locator
            and isinstance(content_hash, str)
            and len(content_hash) == 64
        ):
            return AnchorState.ANCHORED, {
                "document_id": document_id,
                "document_title": citation.get("document_title"),
                "revision_id": citation.get("revision_id"),
                "source_anchor_ids": list(citation.get("source_anchor_ids") or []),
                "locator": locator,
                "identifier": citation.get("identifier"),
                "source_content_hash": row.get("source_content_hash"),
            }
    return AnchorState.ANCHOR_UNAVAILABLE, None


def _taxon_matches(record, accepted_name: str | None, node_key: str) -> bool:
    """The claim must be about the resolved accepted taxon and its graph node."""

    if canonical_name_of(record.taxon.canonical_name) != accepted_name:
        return False
    return record.taxon.node_key in (None, node_key)


def _same_source(record, citation: dict[str, Any]) -> bool:
    """Declared revision and content hash must match what the index holds."""

    if record.source_revision_id is not None and str(citation.get("revision_id")) != record.source_revision_id:
        return False
    return record.content_hash is None or citation.get("source_content_hash") == record.content_hash


def assemble_packet(
    question: ScientificQuestion,
    resolution: TaxonResolution,
    graph: ReadableGraph | None,
    taxon_node_key: Callable[[int], str | None],
    search: SearchFn | None = None,
) -> EvidencePacket:
    gaps: list[str] = []
    if resolution.state not in {
        ResolutionState.RESOLVED_ACCEPTED,
        ResolutionState.RESOLVED_VIA_SYNONYM,
    }:
        gaps.append(f"TAXON_{resolution.state.value}")
        return _empty(question, resolution, None, gaps)
    if graph is None:
        return _empty(question, resolution, None, ["KNOWLEDGE_GRAPH_UNAVAILABLE"])

    view = ReadOnlyGraphView(graph)
    key = taxon_node_key(int(resolution.accepted_canonical_id))
    if key is None:
        return _empty(question, resolution, None, ["TAXON_GRAPH_LINK_UNVERIFIED"])
    focal = view.get_node_by_key(key)
    if focal is None:
        return _empty(question, resolution, key, ["FOCAL_TAXON_NODE_NOT_IN_GRAPH"])
    if canonical_name_of(focal.display_label) != resolution.accepted_name:
        return _empty(question, resolution, key, ["FOCAL_NODE_IDENTITY_MISMATCH"])

    # Filter to the facet's edge types before the bound, so unrelated
    # lower-id edges cannot crowd relevant evidence out of the read.
    facet_edge_types = sorted(
        edge_type
        for edge_type, domain in EDGE_TYPE_DOMAIN.items()
        if domain in FACET_DOMAINS[question.facet]
    )
    edges = view.get_outgoing_edges(
        [focal.kg_node_id], edge_types=facet_edge_types, limit=MAX_GRAPH_RECORDS + 1
    )
    truncated = len(edges) > MAX_GRAPH_RECORDS
    edges = edges[:MAX_GRAPH_RECORDS]
    targets = {n.kg_node_id: n for n in view.get_nodes({e.to_node_id for e in edges})}

    subject = resolution.accepted_name or focal.display_label or key
    items: list[EvidenceItem] = []
    withheld = 0
    anchors_used = 0
    for edge in sorted(edges, key=lambda e: e.kg_edge_id):
        target = targets.get(edge.to_node_id)
        if _withheld(edge, target):
            withheld += 1
            continue
        record, violations = parse_claim_provenance(
            {k: v for k, v in (edge.payload or {}).items() if k in PAYLOAD_ALLOWLIST}
        )
        document_id = record.source_document_id if record else None
        if record is None:
            anchor_state = (
                AnchorState.SOURCE_UNDECLARED
                if violations == ("CLAIM_PROVENANCE_ABSENT",)
                else AnchorState.PROVENANCE_INVALID
            )
            citation = None
        elif not _taxon_matches(record, resolution.accepted_name, key):
            anchor_state, citation = AnchorState.TAXON_BINDING_MISMATCH, None
        elif anchors_used >= MAX_EVIDENCE_RECORDS:
            anchor_state, citation = AnchorState.ANCHOR_UNAVAILABLE, None
            truncated = True
        else:
            anchors_used += 1
            anchor_state, citation = _anchor(search, document_id, subject)
            if anchor_state == AnchorState.ANCHORED and not _same_source(record, citation):
                anchor_state, citation = AnchorState.SOURCE_REVISION_MISMATCH, None
        items.append(
            EvidenceItem(
                ref=f"kg_edge:{edge.kg_edge_id}",
                domain=domain_for_edge_type(edge.edge_type),
                edge_type=edge.edge_type,
                subject=subject,
                object_label=(target.display_label if target else None)
                or f"kg_node:{edge.to_node_id}",
                polarity=_polarity(edge.edge_type),
                evidence_class=edge.evidence_class,
                review_state=(
                    None if record is None else "APPROVED" if record.reviewed else record.review_status.upper()
                ),
                verification_state="VERIFIED" if anchor_state == AnchorState.ANCHORED else None,
                source_table=edge.source_table,
                source_pk=edge.source_pk,
                source_document_id=document_id,
                assertion_id=record.assertion_id if record else None,
                conflicting_assertion_ids=record.conflicting_assertion_ids if record else (),
                qualifier="; ".join(record.qualifiers) if record and record.qualifiers else None,
                anchor_state=anchor_state,
                citation=citation,
                extraction_method=record.extraction_method if record else None,
                confidence=record.confidence if record else None,
                uncertainty=record.uncertainty if record else (),
                declared_anchors=tuple(a.to_dict() for a in record.anchors) if record else (),
                taxon_binding=record.taxon.to_dict() if record else None,
                provenance_violations=violations,
            )
        )

    conflicts = _conflicts(items)
    if withheld:
        gaps.append("SENSITIVE_RECORDS_WITHHELD")
    if truncated:
        gaps.append("RETRIEVAL_LIMIT_REACHED")
    return EvidencePacket(
        contract_version=CONTRACT_VERSION,
        question=question,
        resolution=resolution,
        focal_node_key=key,
        items=tuple(items),
        conflicts=conflicts,
        gaps=tuple(gaps),
        withheld_count=withheld,
        truncated=truncated,
    )


def _conflicts(items: list[EvidenceItem]) -> tuple[tuple[str, str], ...]:
    """Pair items linked by an explicit conflict or by negative polarity.

    Only *declared* conflicts are detected; implicit disagreement (two
    incompatible values with no link) is not inferred by the pilot.
    """

    by_assertion = {i.assertion_id: i.ref for i in items if i.assertion_id}
    pairs: set[tuple[str, str]] = set()
    for item in items:
        for other in item.conflicting_assertion_ids:
            if other in by_assertion and by_assertion[other] != item.ref:
                pairs.add(tuple(sorted((item.ref, by_assertion[other]))))
    negatives = [i for i in items if i.polarity < 0]
    for negative in negatives:
        for item in items:
            if item.polarity > 0 and item.domain == negative.domain:
                pairs.add(tuple(sorted((item.ref, negative.ref))))
    return tuple(sorted(pairs))


def _empty(question, resolution, key, gaps) -> EvidencePacket:
    return EvidencePacket(
        contract_version=CONTRACT_VERSION,
        question=question,
        resolution=resolution,
        focal_node_key=key,
        items=(),
        conflicts=(),
        gaps=tuple(gaps),
        withheld_count=0,
        truncated=False,
    )
