"""Bridge into the existing literature-extraction pipeline.

:class:`MorphologyExtractor` implements the ``Extractor`` contract from
``app.literature_extraction.extractors.base`` so the deterministic morphology
rules run as a first-class pipeline stage alongside the existing metadata,
section, entity, glossary and claim extractors.  Output lands in
``PaperKnowledge`` as typed ``Measurement`` / ``Claim`` / ``Evidence`` /
``Entity`` objects with ``rule_extracted`` provenance, unreviewed status and
exact source spans — the same contracts every other extractor honours.

Configuration (via ``PipelineContext.config.extractor_settings['morphology']``):

* ``taxon_id`` (required): resolved canonical taxon the document describes.
* ``taxon_name``: human-readable name used for the taxon entity.
* ``source_citation``: dict matching ``SourceCitation`` fields; defaults to a
  conservative ``unknown_requires_review`` citation derived from the document.
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.literature_extraction.context import PipelineContext
from app.literature_extraction.extractors.base import Extractor
from app.literature_extraction.ingest import read_text_exact
from app.literature_extraction.models import (
    Claim,
    Entity,
    Evidence,
    Measurement,
    PaperKnowledge,
    Provenance,
    SourceSpan,
)

from .extraction import EXTRACTOR_NAME, EXTRACTOR_VERSION, extract_characters, parse_description_text
from .models import (
    CharacterObservationRecord,
    EvidenceKind,
    ProvenanceMethod,
    SourceCitation,
    StateKind,
)


def _provenance(confidence: float) -> Provenance:
    return Provenance(
        method="rule_extracted",
        confidence=confidence,
        extractor=EXTRACTOR_NAME,
        extractor_version=EXTRACTOR_VERSION,
        review_status="unreviewed",
    )


def _fallback_citation(paper: PaperKnowledge) -> SourceCitation:
    return SourceCitation(
        source_id=paper.paper_id,
        source_name=paper.metadata.title or paper.source.original_filename,
        source_type="literature_document",
        rights_status=paper.source.rights_status,
        attribution=paper.metadata.title or paper.source.original_filename,
        notes="Citation derived from PaperKnowledge; review before redistribution.",
    )


class MorphologyExtractor(Extractor):
    """Pipeline stage: deterministic orchid morphology character extraction."""

    name = "morphology"
    version = EXTRACTOR_VERSION

    async def run(self, context: PipelineContext, paper: PaperKnowledge) -> PaperKnowledge:
        settings = context.config.extractor_settings.get(self.name, {})
        taxon_id = settings.get("taxon_id")
        if not taxon_id:
            raise ValueError(
                "morphology extractor requires extractor_settings['morphology']['taxon_id']; "
                "run taxon resolution upstream and pass the canonical id explicitly"
            )
        citation_payload = settings.get("source_citation")
        citation = (
            SourceCitation(**citation_payload) if citation_payload else _fallback_citation(paper)
        )
        text = read_text_exact(context.source_path)
        parsed = parse_description_text(text, fallback_source_id=citation.source_id)
        # A pipeline-supplied citation outranks fixture front matter; the body
        # text and its raw-file offset are identical either way.
        if citation_payload:
            from .extraction import ParsedDescription

            parsed = ParsedDescription(
                citation=citation,
                taxon_name=parsed.taxon_name,
                body=parsed.body,
                body_offset=parsed.body_offset,
            )

        records = extract_characters(
            parsed,
            taxon_id,
            evidence_kind=EvidenceKind.LITERATURE,
            provenance_method=ProvenanceMethod.RULE_EXTRACTED,
        )
        reported = [record for record in records if record.state_kind in {StateKind.PRESENT, StateKind.ABSENT}]

        taxon_entity = Entity(
            entity_id=f"taxon-{hashlib.sha256(taxon_id.encode()).hexdigest()[:16]}",
            entity_type="taxon",
            name=settings.get("taxon_name") or parsed.taxon_name or taxon_id,
            normalized_name=taxon_id,
            provenance=_provenance(0.9),
        )

        measurements: list[Measurement] = list(paper.measurements)
        claims: list[Claim] = list(paper.claims)
        evidence_items: list[Evidence] = list(paper.evidence)

        for record in reported:
            evidence_id = f"ev-{record.record_id}"
            if record.span is not None:
                # Spans are captured relative to the description body; the
                # pipeline validates them against the full raw document, so
                # re-project by the front-matter offset before emitting.
                raw_start = parsed.body_offset + record.span.start
                raw_end = parsed.body_offset + record.span.end
                evidence_items.append(
                    Evidence(
                        evidence_id=evidence_id,
                        excerpt=record.span.excerpt,
                        span=SourceSpan(char_start=raw_start, char_end=raw_end),
                        evidence_type="text",
                        supports_ids=[record.record_id],
                    )
                )
            statement = _statement(record)
            claims.append(
                Claim(
                    claim_id=record.record_id,
                    statement=statement,
                    claim_type="observation",
                    subject_ids=[taxon_entity.entity_id],
                    predicate=record.character_id,
                    evidence_ids=[evidence_id] if record.span is not None else [],
                    polarity="positive" if record.state_kind == StateKind.PRESENT else "negative",
                    provenance=_provenance(record.confidence),
                )
            )
            if record.value_normalized is not None or isinstance(record.value, (int, float)):
                value: float | None = None
                if isinstance(record.value, (int, float)):
                    value = float(record.value)
                measurements.append(
                    Measurement(
                        measurement_id=f"ms-{record.record_id}",
                        subject_id=taxon_entity.entity_id,
                        property=record.character_id,
                        value=value,
                        value_text=record.span.excerpt if record.span else str(record.value),
                        unit=record.unit_original or record.unit_normalized,
                        evidence_ids=[evidence_id] if record.span is not None else [],
                        provenance=_provenance(record.confidence),
                    )
                )

        entities = list(paper.entities)
        if not any(entity.normalized_name == taxon_id for entity in entities):
            entities.append(taxon_entity)

        return paper.model_copy(
            update={
                "entities": entities,
                "measurements": measurements,
                "claims": claims,
                "evidence": evidence_items,
            }
        )

    def output_count(self, paper: PaperKnowledge) -> int:
        return len(paper.claims) + len(paper.measurements)


def _statement(record: CharacterObservationRecord) -> str:
    if record.state_kind == StateKind.ABSENT:
        return f"{record.character_id}: absent (explicitly stated by source)"
    return f"{record.character_id}: {record.value}"
