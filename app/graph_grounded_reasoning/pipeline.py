"""End-to-end graph-grounded reasoning pilot (read-only, provider-free)."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from runtime.knowledge_graph.canonical_taxonomy import CanonicalRegistry

from .contracts import (
    CONTRACT_VERSION,
    VALIDATOR_VERSION,
    Composition,
    ResultState,
    ScientificQuestion,
)
from .reasoning import Composer, compose
from .resolution import resolve_question_taxon
from .retrieval import ReadableGraph, SearchFn, assemble_packet
from .validation import validate


class GraphGroundedReasoner:
    """Answer one typed scientific question from read-only graph and index reads.

    ``taxon_node_key`` maps a registry ``canonical_id`` to the graph node key,
    or to ``None`` when no verified link exists (``TAXON_GRAPH_LINK_UNVERIFIED``).
    It is required: registry ids are assigned per registry build and are not
    graph ``source_pk`` values, so no mapping may be assumed.  Use
    ``runtime.knowledge_graph.canonical_graph_mapping`` to build one.  The focal node
    must also carry the accepted canonical name, otherwise the packet reports
    ``FOCAL_NODE_IDENTITY_MISMATCH`` instead of reading another taxon's edges.
    """

    def __init__(
        self,
        registry: CanonicalRegistry,
        graph: ReadableGraph | None,
        taxon_node_key: Callable[[int], str | None],
        search: SearchFn | None = None,
        composer: Composer = compose,
    ):
        self.registry = registry
        self.graph = graph
        self.search = search
        self.taxon_node_key = taxon_node_key
        self.composer = composer

    def answer(self, question: ScientificQuestion) -> dict[str, Any]:
        started = time.perf_counter()
        resolution = resolve_question_taxon(question.text, self.registry)
        packet = assemble_packet(
            question, resolution, self.graph, self.taxon_node_key, self.search
        )
        retrieved = time.perf_counter()
        composition: Composition = self.composer(packet)
        violations = validate(packet, composition)
        state = ResultState.VALIDATION_FAILED if violations else composition.state
        claims = [] if violations else [c.to_dict() for c in composition.claims]
        cited = {ref for c in claims for ref in c["refs"]}
        finished = time.perf_counter()
        return {
            "contract_version": CONTRACT_VERSION,
            "question": {"text": question.text, "facet": question.facet.value},
            "resolution": resolution.to_dict(),
            "state": state.value,
            "claims": claims,
            "citations": {
                ref: packet.item(ref).citation for ref in sorted(cited)
            },
            "conflicts": [list(p) for p in composition.conflicts],
            "uncertainty": list(composition.uncertainty),
            "gaps": list(composition.gaps),
            "evidence_packet": packet.to_dict(),
            "validation": {
                "validator_version": VALIDATOR_VERSION,
                "composer_version": composition.composer_version,
                "passed": not violations,
                "violations": list(violations),
            },
            "governance": {
                "review_required": True,
                "reviewed_conclusion": False,
                "published": False,
                "knowledge_graph_mutation": False,
                # Known only for the built-in deterministic composer.
                "provider_calls": 0 if self.composer is compose else None,
                "confidence_is_probability": False,
            },
            "timings_ms": {
                "retrieval": round((retrieved - started) * 1000, 3),
                "total": round((finished - started) * 1000, 3),
            },
        }
