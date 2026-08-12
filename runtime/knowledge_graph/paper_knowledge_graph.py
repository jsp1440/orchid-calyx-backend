"""Convert literature-extraction ``PaperKnowledge`` into governed graph specs.

The converter is pure: it creates ``NodeSpec``/``EdgeSpec`` values and never writes
to a repository.  Publication of the returned specs remains a separate governed
operation.

Scientific claims and measurements fail closed by default.  Only objects whose
extraction provenance is human-reviewed as ``accepted`` or ``corrected`` are
included unless ``include_candidates=True`` is explicitly requested.  Candidate
objects retain their review status and must never be mistaken for published
knowledge merely because they can be represented as graph specs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from app.literature_extraction.models import PaperKnowledge, Provenance, SourceSpan

from .publisher import EdgeSpec, NodeSpec, canonical_key
from .scientific_method_vocabulary import CLAIM_TYPE_TO_NODE_TYPE

SOURCE_TABLE = "literature_extraction.paper_knowledge"
_REVIEWED = {"accepted", "corrected"}


@dataclass(frozen=True, slots=True)
class PaperGraphBundle:
    nodes: tuple[NodeSpec, ...]
    edges: tuple[EdgeSpec, ...]
    candidate_objects_omitted: int
    publication_key: str


def _span_payload(span: SourceSpan) -> dict[str, object | None]:
    return {
        "page_start": span.page_start,
        "page_end": span.page_end,
        "section_id": span.section_id,
        "char_start": span.char_start,
        "char_end": span.char_end,
    }


def _reviewed(provenance: Provenance, include_candidates: bool) -> bool:
    return include_candidates or provenance.review_status in _REVIEWED


def _confidence(provenance: Provenance) -> float:
    return float(provenance.confidence)


def build_paper_graph_specs(
    paper: PaperKnowledge,
    *,
    taxon_keys_by_entity_id: Mapping[str, str] | None = None,
    include_candidates: bool = False,
) -> PaperGraphBundle:
    """Return deterministic graph specs for a parsed scientific paper.

    ``taxon_keys_by_entity_id`` must be supplied by a canonical taxonomy resolver;
    this converter never creates or fuzzy-matches taxonomy nodes from paper text.
    """
    taxon_keys = dict(taxon_keys_by_entity_id or {})
    nodes: list[NodeSpec] = []
    edges: list[EdgeSpec] = []
    omitted = 0

    publication_key = canonical_key("publication", paper.paper_id)
    doi = next(
        (identifier.value for identifier in paper.metadata.identifiers if identifier.scheme == "doi"),
        None,
    )
    nodes.append(NodeSpec(
        node_type="publication",
        source_pk=paper.paper_id,
        display_label=paper.metadata.title or paper.paper_id,
        source_table=SOURCE_TABLE,
        evidence_class="source_document",
        payload={
            "title": paper.metadata.title,
            "authors": list(paper.metadata.authors),
            "journal": paper.metadata.journal,
            "publication_year": paper.metadata.publication_year,
            "doi": doi,
            "content_hash": paper.source.content_hash,
            "storage_uri": paper.source.storage_uri,
            "analysis_id": paper.analysis_manifest.analysis_id,
            "analysis_status": paper.analysis_manifest.status,
            "pipeline_version": paper.analysis_manifest.pipeline_version,
        },
    ))

    # Canonical taxa are never authored by this converter. A caller may provide
    # exact resolved taxon graph keys for extracted taxon entities.
    for entity in paper.entities:
        if entity.entity_type != "taxon":
            continue
        taxon_key = taxon_keys.get(entity.entity_id)
        if taxon_key:
            edges.append(EdgeSpec(
                edge_type="documented_by",
                from_key=taxon_key,
                to_key=publication_key,
                source_table=SOURCE_TABLE,
                source_pk=f"{paper.paper_id}:{entity.entity_id}",
                evidence_class=entity.provenance.method,
                confidence_score=_confidence(entity.provenance),
                confidence_label=entity.provenance.review_status,
                rule_name="paper_exact_taxon_resolution",
                payload={"entity_name": entity.name},
            ))

    for section in paper.sections:
        key = canonical_key("paper_section", f"{paper.paper_id}:{section.section_id}")
        nodes.append(NodeSpec(
            node_type="paper_section",
            source_pk=f"{paper.paper_id}:{section.section_id}",
            display_label=section.heading or section.canonical_type,
            source_table=SOURCE_TABLE,
            evidence_class="source_section",
            payload={
                "canonical_type": section.canonical_type,
                "order": section.order,
                "text": section.text,
                "span": _span_payload(section.span),
            },
        ))
        edges.append(EdgeSpec(
            edge_type="has_section",
            from_key=publication_key,
            to_key=key,
            source_table=SOURCE_TABLE,
            source_pk=f"{paper.paper_id}:{section.section_id}",
            rule_name="paper_section_structure",
        ))

    evidence_keys: dict[str, str] = {}
    for evidence in paper.evidence:
        key = canonical_key("evidence", f"{paper.paper_id}:{evidence.evidence_id}")
        evidence_keys[evidence.evidence_id] = key
        nodes.append(NodeSpec(
            node_type="evidence",
            source_pk=f"{paper.paper_id}:{evidence.evidence_id}",
            display_label=evidence.excerpt[:160],
            source_table=SOURCE_TABLE,
            evidence_class=evidence.evidence_type,
            payload={
                "excerpt": evidence.excerpt,
                "evidence_type": evidence.evidence_type,
                "span": _span_payload(evidence.span),
                "supports_ids": list(evidence.supports_ids),
                "contradicts_ids": list(evidence.contradicts_ids),
            },
        ))
        edges.append(EdgeSpec(
            edge_type="extracted_from",
            from_key=key,
            to_key=publication_key,
            source_table=SOURCE_TABLE,
            source_pk=f"{paper.paper_id}:{evidence.evidence_id}",
            rule_name="paper_evidence_source",
        ))

    claim_keys: dict[str, str] = {}
    for claim in paper.claims:
        if not _reviewed(claim.provenance, include_candidates):
            omitted += 1
            continue
        node_type = CLAIM_TYPE_TO_NODE_TYPE[claim.claim_type]
        source_pk = f"{paper.paper_id}:{claim.claim_id}"
        key = canonical_key(node_type, source_pk)
        claim_keys[claim.claim_id] = key
        nodes.append(NodeSpec(
            node_type=node_type,
            source_pk=source_pk,
            display_label=claim.statement[:240],
            source_table=SOURCE_TABLE,
            evidence_class=claim.provenance.method,
            confidence_score=_confidence(claim.provenance),
            confidence_label=claim.provenance.review_status,
            payload={
                "statement": claim.statement,
                "claim_type": claim.claim_type,
                "polarity": claim.polarity,
                "predicate": claim.predicate,
                "subject_ids": list(claim.subject_ids),
                "object_ids": list(claim.object_ids),
            },
        ))
        primary_edge = {
            "observation": "has_observation",
            "result": "reports_result",
            "hypothesis": "tests_hypothesis",
            "methodological": "uses_method",
            "limitation": "states_limitation",
            "recommendation": "makes_recommendation",
        }.get(claim.claim_type, "extracted_from")
        if primary_edge == "extracted_from":
            from_key, to_key = key, publication_key
        else:
            from_key, to_key = publication_key, key
        edges.append(EdgeSpec(
            edge_type=primary_edge,
            from_key=from_key,
            to_key=to_key,
            source_table=SOURCE_TABLE,
            source_pk=source_pk,
            evidence_class=claim.provenance.method,
            confidence_score=_confidence(claim.provenance),
            confidence_label=claim.provenance.review_status,
            rule_name="paper_reviewed_claim",
        ))
        for evidence_id in claim.evidence_ids:
            evidence_key = evidence_keys.get(evidence_id)
            if evidence_key:
                edges.append(EdgeSpec(
                    edge_type="supported_by_evidence",
                    from_key=key,
                    to_key=evidence_key,
                    source_table=SOURCE_TABLE,
                    source_pk=f"{source_pk}:{evidence_id}",
                    rule_name="paper_claim_evidence",
                ))

    for measurement in paper.measurements:
        if not _reviewed(measurement.provenance, include_candidates):
            omitted += 1
            continue
        source_pk = f"{paper.paper_id}:{measurement.measurement_id}"
        key = canonical_key("measurement", source_pk)
        nodes.append(NodeSpec(
            node_type="measurement",
            source_pk=source_pk,
            display_label=f"{measurement.property}: {measurement.value_text}",
            source_table=SOURCE_TABLE,
            evidence_class=measurement.provenance.method,
            confidence_score=_confidence(measurement.provenance),
            confidence_label=measurement.provenance.review_status,
            payload={
                "subject_id": measurement.subject_id,
                "property": measurement.property,
                "value": measurement.value,
                "value_text": measurement.value_text,
                "unit": measurement.unit,
                "qualifier": measurement.qualifier,
                "sample_size": measurement.sample_size,
            },
        ))
        edges.append(EdgeSpec(
            edge_type="has_measurement",
            from_key=publication_key,
            to_key=key,
            source_table=SOURCE_TABLE,
            source_pk=source_pk,
            evidence_class=measurement.provenance.method,
            confidence_score=_confidence(measurement.provenance),
            confidence_label=measurement.provenance.review_status,
            rule_name="paper_reviewed_measurement",
        ))
        for evidence_id in measurement.evidence_ids:
            evidence_key = evidence_keys.get(evidence_id)
            if evidence_key:
                edges.append(EdgeSpec(
                    edge_type="extracted_from",
                    from_key=key,
                    to_key=evidence_key,
                    source_table=SOURCE_TABLE,
                    source_pk=f"{source_pk}:{evidence_id}",
                    rule_name="paper_measurement_evidence",
                ))

    for reference in paper.references:
        source_pk = f"{paper.paper_id}:{reference.reference_id}"
        key = canonical_key("reference", source_pk)
        nodes.append(NodeSpec(
            node_type="reference",
            source_pk=source_pk,
            display_label=reference.title or reference.raw_citation[:240],
            source_table=SOURCE_TABLE,
            evidence_class="bibliographic_reference",
            payload={
                "raw_citation": reference.raw_citation,
                "title": reference.title,
                "authors": list(reference.authors),
                "year": reference.year,
                "identifiers": [item.model_dump(mode="json") for item in reference.identifiers],
                "resolved": reference.resolved,
            },
        ))
        edges.append(EdgeSpec(
            edge_type="cites",
            from_key=publication_key,
            to_key=key,
            source_table=SOURCE_TABLE,
            source_pk=source_pk,
            rule_name="paper_reference",
        ))

    for figure in paper.figures:
        source_pk = f"{paper.paper_id}:{figure.figure_id}"
        key = canonical_key("figure_evidence", source_pk)
        nodes.append(NodeSpec(
            node_type="figure_evidence",
            source_pk=source_pk,
            display_label=figure.label or figure.caption or figure.figure_id,
            source_table=SOURCE_TABLE,
            evidence_class="figure",
            payload={
                "caption": figure.caption,
                "page": figure.page,
                "asset_uri": figure.asset_uri,
                "entity_ids": list(figure.entity_ids),
                "evidence_ids": list(figure.evidence_ids),
            },
        ))
        edges.append(EdgeSpec(
            edge_type="has_figure_evidence",
            from_key=publication_key,
            to_key=key,
            source_table=SOURCE_TABLE,
            source_pk=source_pk,
            rule_name="paper_figure",
        ))

    for table in paper.tables:
        source_pk = f"{paper.paper_id}:{table.table_id}"
        key = canonical_key("table_evidence", source_pk)
        nodes.append(NodeSpec(
            node_type="table_evidence",
            source_pk=source_pk,
            display_label=table.label or table.caption or table.table_id,
            source_table=SOURCE_TABLE,
            evidence_class="table",
            payload={
                "caption": table.caption,
                "page": table.page,
                "columns": list(table.columns),
                "rows": list(table.rows),
                "evidence_ids": list(table.evidence_ids),
            },
        ))
        edges.append(EdgeSpec(
            edge_type="has_table_evidence",
            from_key=publication_key,
            to_key=key,
            source_table=SOURCE_TABLE,
            source_pk=source_pk,
            rule_name="paper_table",
        ))

    return PaperGraphBundle(
        nodes=tuple(nodes),
        edges=tuple(edges),
        candidate_objects_omitted=omitted,
        publication_key=publication_key,
    )
