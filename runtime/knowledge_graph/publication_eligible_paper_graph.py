"""Strict graph projection for publication-eligible literature extraction.

``build_paper_graph_specs`` is intentionally useful for staging and candidate
inspection.  This module is the stricter publication-side projection: scientific
claims are included only when a normalized evidence record for that claim has an
explicit ``eligible_for_publication`` decision.  Source structure (publication,
sections, evidence spans, references, figures, tables) remains representable,
while reviewed measurements continue to use their own provenance review state.

The function is pure and never mutates the Knowledge Graph.
"""

from __future__ import annotations

from typing import Mapping

from app.literature_extraction.models import PaperKnowledge

from .paper_knowledge_graph import PaperGraphBundle, build_paper_graph_specs
from .publisher import EdgeSpec, canonical_key
from .scientific_method_vocabulary import CLAIM_TYPE_TO_NODE_TYPE

_REVIEWED = {"accepted", "corrected"}


def _publication_eligible_claim_ids(paper: PaperKnowledge) -> set[str]:
    eligible_record_ids = {
        decision.source_record_id
        for decision in paper.publication_decisions
        if decision.status == "eligible_for_publication"
    }
    return {
        record.source_claim_id
        for record in paper.normalized_evidence_records
        if record.record_id in eligible_record_ids
    }


def _reviewed_entity_ids(paper: PaperKnowledge) -> set[str]:
    return {
        entity.entity_id
        for entity in paper.entities
        if entity.provenance.review_status in _REVIEWED
    }


def build_publication_eligible_paper_graph_specs(
    paper: PaperKnowledge,
    *,
    taxon_keys_by_entity_id: Mapping[str, str] | None = None,
) -> PaperGraphBundle:
    """Return a fail-closed graph bundle suitable for governed publication review.

    Claims require an explicit publication-eligible normalized evidence record.
    Taxon links require either a reviewed entity or an entity used by an eligible
    claim.  This keeps exact taxonomy resolution useful without allowing an
    unreviewed entity extraction to create a free-standing ``documented_by`` edge.
    """
    taxon_keys = dict(taxon_keys_by_entity_id or {})
    base = build_paper_graph_specs(
        paper,
        taxon_keys_by_entity_id=taxon_keys,
        include_candidates=False,
    )
    eligible_claim_ids = _publication_eligible_claim_ids(paper)

    blocked_claim_keys: set[str] = set()
    for claim in paper.claims:
        if claim.claim_id in eligible_claim_ids:
            continue
        blocked_claim_keys.add(
            canonical_key(
                CLAIM_TYPE_TO_NODE_TYPE[claim.claim_type],
                f"{paper.paper_id}:{claim.claim_id}",
            )
        )

    nodes = [node for node in base.nodes if node.key() not in blocked_claim_keys]
    edges = [
        edge
        for edge in base.edges
        if edge.from_key not in blocked_claim_keys and edge.to_key not in blocked_claim_keys
    ]

    eligible_entity_ids = _reviewed_entity_ids(paper)
    for claim in paper.claims:
        if claim.claim_id in eligible_claim_ids:
            eligible_entity_ids.update(claim.subject_ids)
            eligible_entity_ids.update(claim.object_ids)

    safe_documented_source_pks = {
        f"{paper.paper_id}:{entity_id}" for entity_id in eligible_entity_ids
    }
    edges = [
        edge
        for edge in edges
        if edge.edge_type != "documented_by"
        or edge.source_pk in safe_documented_source_pks
    ]

    node_keys = {node.key() for node in nodes}
    extra_edges: list[EdgeSpec] = []

    for claim in paper.claims:
        if claim.claim_id not in eligible_claim_ids:
            continue
        claim_key = canonical_key(
            CLAIM_TYPE_TO_NODE_TYPE[claim.claim_type],
            f"{paper.paper_id}:{claim.claim_id}",
        )
        if claim_key not in node_keys:
            continue
        roles = (("subject", claim.subject_ids), ("object", claim.object_ids))
        for role, entity_ids in roles:
            for entity_id in entity_ids:
                taxon_key = taxon_keys.get(entity_id)
                if not taxon_key:
                    continue
                extra_edges.append(
                    EdgeSpec(
                        edge_type="about_taxon",
                        from_key=claim_key,
                        to_key=taxon_key,
                        source_table="literature_extraction.paper_knowledge",
                        source_pk=f"{paper.paper_id}:{claim.claim_id}:{role}:{entity_id}",
                        evidence_class=claim.provenance.method,
                        confidence_score=float(claim.provenance.confidence),
                        confidence_label="publication_eligible",
                        rule_name="paper_publication_eligible_claim_taxon",
                        payload={
                            "entity_id": entity_id,
                            "semantic_role": role,
                            "publication_eligible": True,
                        },
                    )
                )

    for measurement in paper.measurements:
        if measurement.provenance.review_status not in _REVIEWED:
            continue
        measurement_key = canonical_key(
            "measurement", f"{paper.paper_id}:{measurement.measurement_id}"
        )
        taxon_key = taxon_keys.get(measurement.subject_id)
        if measurement_key not in node_keys or not taxon_key:
            continue
        extra_edges.append(
            EdgeSpec(
                edge_type="measurement_of",
                from_key=measurement_key,
                to_key=taxon_key,
                source_table="literature_extraction.paper_knowledge",
                source_pk=(
                    f"{paper.paper_id}:{measurement.measurement_id}:"
                    f"{measurement.subject_id}"
                ),
                evidence_class=measurement.provenance.method,
                confidence_score=float(measurement.provenance.confidence),
                confidence_label=measurement.provenance.review_status,
                rule_name="paper_reviewed_measurement_taxon",
                payload={"subject_entity_id": measurement.subject_id},
            )
        )

    existing = {
        (edge.edge_type, edge.from_key, edge.to_key, str(edge.source_pk)) for edge in edges
    }
    for edge in extra_edges:
        identity = (edge.edge_type, edge.from_key, edge.to_key, str(edge.source_pk))
        if identity not in existing:
            edges.append(edge)
            existing.add(identity)

    publication_ineligible = sum(
        claim.provenance.review_status in _REVIEWED
        and claim.claim_id not in eligible_claim_ids
        for claim in paper.claims
    )
    return PaperGraphBundle(
        nodes=tuple(nodes),
        edges=tuple(edges),
        candidate_objects_omitted=base.candidate_objects_omitted + publication_ineligible,
        publication_key=base.publication_key,
    )
