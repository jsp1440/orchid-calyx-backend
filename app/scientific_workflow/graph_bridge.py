"""Knowledge Graph bridge (offline).

Builds typed graph nodes and edges with the existing
``runtime.knowledge_graph.models`` dataclasses: taxa, Matrix characters,
lexicon terms and evidence sources become nodes; character observations become
evidence-linked edges whose payloads keep the full provenance (source, span,
method, extractor version).  Node/edge ids are deterministic so re-running the
workflow reproduces the identical graph slice.

Nothing here publishes: production publication goes through the governed
publisher (``runtime/knowledge_graph/publisher.py``) after review — this
bridge only prepares the graph-shaped payload and proves traversal works.
"""

from __future__ import annotations

from typing import Any, Iterable

from runtime.knowledge_graph.models import Edge, Node

from .evidence import CharacterEvidenceStore
from .extraction import CHARACTERS, CharacterDefinition
from .models import StateKind
from .taxonomy import TaxonRecord
from .terminology import TerminologyService

BRIDGE_VERSION = "scientific-workflow-graph-bridge-001"


def _node_id(*parts: str) -> int:
    # Deterministic 62-bit id; stable across runs for identical inputs.
    import hashlib

    digest = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()
    return int(digest[:15], 16)


class GraphSlice:
    """A small in-memory graph slice with traversal helpers."""

    def __init__(self, nodes: Iterable[Node], edges: Iterable[Edge]) -> None:
        self.nodes: dict[int, Node] = {node.kg_node_id: node for node in nodes}
        self.edges: list[Edge] = list(edges)

    def neighbors(self, node_id: int) -> list[tuple[Edge, Node]]:
        result: list[tuple[Edge, Node]] = []
        for edge in self.edges:
            if edge.from_node_id == node_id and edge.to_node_id in self.nodes:
                result.append((edge, self.nodes[edge.to_node_id]))
            elif edge.to_node_id == node_id and edge.from_node_id in self.nodes:
                result.append((edge, self.nodes[edge.from_node_id]))
        return result

    def nodes_of_type(self, node_type: str) -> list[Node]:
        return [node for node in self.nodes.values() if node.node_type == node_type]

    def as_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [edge.to_dict() for edge in self.edges],
            "bridge": BRIDGE_VERSION,
        }


def build_graph_slice(
    store: CharacterEvidenceStore,
    taxa: Iterable[TaxonRecord],
    terminology: TerminologyService,
    definitions: Iterable[CharacterDefinition] = CHARACTERS,
) -> GraphSlice:
    definitions = list(definitions)
    nodes: dict[int, Node] = {}
    edges: list[Edge] = []

    def add_node(node: Node) -> Node:
        nodes[node.kg_node_id] = node
        return node

    character_nodes: dict[str, Node] = {}
    for definition in definitions:
        character_nodes[definition.character_id] = add_node(
            Node(
                kg_node_id=_node_id("character", definition.character_id),
                node_type="matrix_character",
                canonical_key=f"character:{definition.character_id}",
                display_label=definition.label,
                source_table="scientific_workflow.character_schema",
                source_pk=definition.character_id,
                evidence_class="character_definition",
                payload={
                    "value_type": definition.value_type,
                    "weight": definition.weight,
                    "lexicon_term_id": definition.lexicon_term_id,
                    "oao_entity_key": definition.oao_entity_key,
                    "oao_quality_key": definition.oao_quality_key,
                },
            )
        )

    lexicon_nodes: dict[str, Node] = {}
    for definition in definitions:
        if not definition.lexicon_term_id or definition.lexicon_term_id in lexicon_nodes:
            continue
        term = terminology.get(definition.lexicon_term_id)
        if term is None:
            continue
        accessions = [row for row in terminology.accessions_for(term.term_id) if row.is_usable]
        extension_gaps = [
            row.candidate_key
            for row in terminology.accessions_for(term.term_id)
            if row.status == "extension_required"
        ]
        lexicon_nodes[term.term_id] = add_node(
            Node(
                kg_node_id=_node_id("lexicon_term", term.term_id),
                node_type="lexicon_term",
                canonical_key=f"lexicon:{term.term_id}",
                display_label=term.canonical_term,
                source_table="scientific_workflow.lexicon_fixture",
                source_pk=term.term_id,
                evidence_class="terminology",
                payload={
                    "slug": term.slug,
                    "category": term.category,
                    "synonyms": list(term.synonyms),
                    "external_accessions": [row.__dict__ for row in accessions],
                    "oao_extension_gaps": extension_gaps,
                },
            )
        )
        character_node = character_nodes[definition.character_id]
        lexicon_node = lexicon_nodes[term.term_id]
        edges.append(
            Edge(
                kg_edge_id=_node_id("edge", "defined_by", definition.character_id, term.term_id),
                edge_type="character_defined_by_term",
                from_node_id=character_node.kg_node_id,
                to_node_id=lexicon_node.kg_node_id,
                source_table="scientific_workflow.character_schema",
                source_pk=definition.character_id,
                rule_name=BRIDGE_VERSION,
                payload={"lexicon_term_id": term.term_id},
            )
        )

    for taxon in taxa:
        taxon_node = add_node(
            Node(
                kg_node_id=_node_id("taxon", taxon.taxon_id),
                node_type="taxon",
                canonical_key=f"taxon:{taxon.taxon_id}",
                display_label=taxon.full_scientific_name,
                source_table="scientific_workflow.taxon_fixture",
                source_pk=taxon.taxon_id,
                evidence_class="taxonomy_fixture",
                payload={"family": taxon.family, "synonyms": list(taxon.synonyms)},
            )
        )
        views = store.views_for_taxon(taxon.taxon_id, [d.character_id for d in definitions])
        for view in views:
            if view.state_kind in {StateKind.UNKNOWN, StateKind.INAPPLICABLE}:
                continue
            for record in view.records:
                source_node = add_node(
                    Node(
                        kg_node_id=_node_id("source", record.source.source_id),
                        node_type="evidence_source",
                        canonical_key=f"source:{record.source.source_id}",
                        display_label=record.source.source_name,
                        source_table="scientific_workflow.sources",
                        source_pk=record.source.source_id,
                        evidence_class=record.source.source_type,
                        payload=record.source.as_dict(),
                    )
                )
                character_node = character_nodes[view.character_id]
                edges.append(
                    Edge(
                        kg_edge_id=_node_id("edge", "exhibits", record.record_id),
                        edge_type="taxon_exhibits_character",
                        from_node_id=taxon_node.kg_node_id,
                        to_node_id=character_node.kg_node_id,
                        source_table="scientific_workflow.character_evidence",
                        source_pk=record.record_id,
                        evidence_class=str(record.evidence_kind),
                        confidence_score=record.confidence,
                        rule_name=BRIDGE_VERSION,
                        payload={
                            "state_kind": str(view.state_kind),
                            "value": record.value,
                            "value_normalized": record.value_normalized,
                            "unit_normalized": record.unit_normalized,
                            "span": record.span.as_dict() if record.span else None,
                            "provenance_method": str(record.provenance_method),
                            "review_status": record.review_status,
                        },
                    )
                )
                edges.append(
                    Edge(
                        kg_edge_id=_node_id("edge", "sourced_from", record.record_id),
                        edge_type="observation_sourced_from",
                        from_node_id=character_node.kg_node_id,
                        to_node_id=source_node.kg_node_id,
                        source_table="scientific_workflow.character_evidence",
                        source_pk=record.record_id,
                        rule_name=BRIDGE_VERSION,
                        payload={"record_id": record.record_id},
                    )
                )
    return GraphSlice(nodes.values(), edges)
