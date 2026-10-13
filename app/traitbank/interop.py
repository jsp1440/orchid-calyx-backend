"""Identifiers and shapes TraitBank shares with the Knowledge Graph and Calyx.

Two in-flight lanes consume TraitBank evidence:

- **#901 (KG materialization).** Its reviewed-literature projection keys a
  measurement node ``measurement:{paper_id}:{measurement_id}`` and a claim node
  ``{CLAIM_TYPE_TO_NODE_TYPE[claim_type]}:{paper_id}:{claim_id}``
  (``runtime.knowledge_graph.publisher.canonical_key``). TraitBank records the
  same key for every literature assertion it stores, so a TraitBank record and
  a graph node for the same source record are joinable without inference.
- **#1819 (graph-grounded reasoning).** Its ``EvidencePacket`` copies exactly
  ``assertion_id``, ``conflicting_assertion_ids``, ``source_document_id``,
  ``review_state``, ``verification_state`` and ``qualifier`` from a graph edge
  payload. :func:`graph_edge_payload` produces those keys, and
  :func:`evidence_item` produces an ``EvidenceItem.to_dict()``-shaped record so
  Calyx can read TraitBank evidence directly, through the same validator.

The assertion level, scope basis and confidence state travel in ``qualifier``,
the one free field #1819 already allows, so a specimen measurement cannot be
read as a species trait downstream.

Taxa: TraitBank's ``taxon_id`` is the canonical ``taxonomy_id``. The graph's
taxon node for it is the ``oc_graph.kg_nodes`` row with ``node_type='taxon'``
and ``source_pk = taxonomy_id`` (the join the governed Matrix and trait sources
already use). :func:`taxon_graph_nodes` reads that mapping; it never infers one.
"""

from __future__ import annotations

from typing import Any

from psycopg import sql

from .models import AssertionIn

#: Mirrors ``CLAIM_TYPE_TO_NODE_TYPE`` in #901's
#: ``runtime/knowledge_graph/scientific_method_vocabulary.py`` (head
#: ecaecc92ae5d90b7b193fd07aaeb97aa6f9c938c). Once that module is on the base,
#: tests/test_traitbank_interop.py compares the two and fails on any drift.
KG_CLAIM_NODE_TYPES: dict[str, str] = {
    "observation": "observation",
    "result": "result",
    "interpretation": "assertion",
    "hypothesis": "hypothesis",
    "methodological": "method",
    "background": "assertion",
    "limitation": "limitation",
    "recommendation": "recommendation",
}

#: ``PAYLOAD_ALLOWLIST`` in #1819 ``app/graph_grounded_reasoning/contracts.py``
#: (head c9da136668b521d90fae065f2c6cbc4d3b6a3cf9).
GGR_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {
        "assertion_id",
        "conflicting_assertion_ids",
        "source_document_id",
        "review_state",
        "verification_state",
        "qualifier",
    }
)

#: ``EvidenceItem.to_dict()`` keys in #1819 (same head).
GGR_EVIDENCE_ITEM_KEYS: frozenset[str] = frozenset(
    {
        "ref",
        "domain",
        "edge_type",
        "subject",
        "object_label",
        "polarity",
        "evidence_class",
        "review_state",
        "verification_state",
        "provenance",
        "conflicting_assertion_ids",
        "qualifier",
        "anchor_state",
        "citation",
    }
)

TRAITS_DOMAIN = "traits"  # runtime.knowledge_graph.vocabulary domain for has_trait


def kg_measurement_key(paper_id: str, measurement_id: str) -> str:
    return f"measurement:{paper_id}:{measurement_id}"


def kg_claim_key(paper_id: str, claim_id: str, claim_type: str) -> str | None:
    node_type = KG_CLAIM_NODE_TYPES.get(claim_type)
    return f"{node_type}:{paper_id}:{claim_id}" if node_type else None


def edge_type_for(a: AssertionIn) -> str:
    return "has_trait" if a.level == "taxon" else "has_trait_evidence_from_individuals"


def qualifier(a: AssertionIn) -> str:
    """Level, scope and confidence state, in the one field #1819 keeps."""
    confidence_state = "reported" if a.confidence is not None else "unknown"
    return f"assertion_level={a.level};scope_basis={a.scope_basis};confidence_state={confidence_state}"


def graph_edge_payload(
    a: AssertionIn, *, source_document_id: str, conflicting: list[str]
) -> dict[str, Any]:
    """Payload for a KG edge carrying this assertion (#901 publisher, #1819 reader)."""
    return {
        "assertion_id": a.assertion_id,
        "conflicting_assertion_ids": sorted(conflicting),
        "source_document_id": source_document_id,
        "review_state": a.provenance.review_status,
        "verification_state": a.evidence_state,
        "qualifier": qualifier(a),
    }


def evidence_item(
    a: AssertionIn,
    *,
    subject: str,
    object_label: str,
    source_document_id: str,
    conflicting: list[str],
) -> dict[str, Any]:
    """An ``EvidenceItem.to_dict()``-shaped record for #1819's packet and validator."""
    anchored = bool(a.provenance.original_text)
    return {
        "ref": f"traitbank:{a.assertion_id}",
        "domain": TRAITS_DOMAIN,
        "edge_type": edge_type_for(a),
        "subject": subject,
        "object_label": object_label,
        "polarity": 1,
        "evidence_class": a.provenance.evidence_type,
        "review_state": a.provenance.review_status,
        "verification_state": a.evidence_state,
        "provenance": {
            "source_table": "oc_traitbank.assertions",
            "source_pk": a.assertion_id,
            "source_document_id": source_document_id,
            "assertion_id": a.assertion_id,
        },
        "conflicting_assertion_ids": sorted(conflicting),
        "qualifier": qualifier(a),
        # The verbatim source excerpt is stored with the record, so the
        # citation is anchored without a retrieval lookup.
        "anchor_state": "ANCHORED" if anchored else "SOURCE_UNDECLARED",
        "citation": {
            "citation": a.provenance.citation,
            "locator": a.provenance.locator,
            "excerpt": a.provenance.original_text,
            "license": a.provenance.license,
            "source_url": a.provenance.source_url,
        }
        if anchored
        else None,
    }


def taxon_graph_nodes(
    cur: Any, taxonomy_ids: list[str]
) -> dict[str, dict[str, Any]] | None:
    """KG taxon node per canonical taxonomy id, or ``None`` when no graph exists.

    Uses the existing convention (``kg_nodes.node_type='taxon'`` and
    ``source_pk = taxonomy_id``). Ids with no node, or with more than one
    active node, are left out rather than guessed.
    """
    cur.execute("SELECT to_regclass('oc_graph.kg_nodes') IS NOT NULL")
    if not cur.fetchone()[0]:
        return None
    cur.execute(
        sql.SQL(
            "SELECT source_pk, kg_node_id, canonical_key, display_label FROM oc_graph.kg_nodes "
            "WHERE node_type = 'taxon' AND COALESCE(is_active, true) AND source_pk = ANY(%s)"
        ),
        ([str(t) for t in taxonomy_ids],),
    )
    found: dict[str, list[tuple]] = {}
    for source_pk, node_id, key, label in cur.fetchall():
        found.setdefault(str(source_pk), []).append((node_id, key, label))
    return {
        taxon: {
            "kg_node_id": rows[0][0],
            "canonical_key": rows[0][1],
            "display_label": rows[0][2],
        }
        for taxon, rows in found.items()
        if len(rows) == 1
    }
