from __future__ import annotations

import hashlib
from dataclasses import asdict
from typing import Any

from app.literature_extraction.models import PaperKnowledge
from app.literature_extraction.source_binding import CanonicalLiteratureSourceBinding
from .models import (
    BibliographicRecord,
    EvidenceAnchor,
    EvidenceClass,
    EvidenceMatrixRow,
    VerificationState,
)


VERIFIED = {
    VerificationState.VERIFIED_AUTHORITY,
    VerificationState.VERIFIED_PUBLISHER,
}


def _clean(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def _normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :].strip()
    return normalized or None


def _bibliography_matches_paper(
    paper: PaperKnowledge, bibliography: BibliographicRecord
) -> bool:
    paper_dois = {
        normalized
        for identifier in paper.metadata.identifiers
        if identifier.scheme == "doi"
        if (normalized := _normalize_doi(identifier.value)) is not None
    }
    bibliography_doi = _normalize_doi(bibliography.doi)
    if paper_dois:
        return bibliography_doi in paper_dois
    if paper.metadata.title:
        return _clean(bibliography.title) == _clean(paper.metadata.title)
    return False


def _expected_integrity_proof(
    *, evidence: Any, anchor_id: int, source_hash: str
) -> dict[str, Any]:
    return {
        "anchor_id": anchor_id,
        "source_hash": source_hash,
        "excerpt_hash": hashlib.sha256(evidence.excerpt.encode()).hexdigest(),
        "char_start": evidence.span.char_start,
        "char_end": evidence.span.char_end,
        "section_id": evidence.span.section_id,
        "evidence_type": evidence.evidence_type,
    }


class EvidenceMatrixBuilder:
    """Map original source-bound literature evidence into conservative study rows.

    Automatic extraction deliberately defaults to OBSERVATIONAL. A stronger design
    class such as CONTROLLED_EXPERIMENT or DIRECT_TRACER requires a later reviewed
    classification rather than being inferred from persuasive prose.
    """

    def build(
        self,
        *,
        paper: PaperKnowledge,
        binding: CanonicalLiteratureSourceBinding,
        bibliography: BibliographicRecord,
    ) -> dict[str, Any]:
        if bibliography.verification_state not in VERIFIED:
            raise ValueError("VERIFIED_BIBLIOGRAPHY_REQUIRED")
        if not (bibliography.verification_provider or "").strip() or not (
            bibliography.verification_identifier or ""
        ).strip():
            raise ValueError("BIBLIOGRAPHIC_VERIFICATION_PROVENANCE_REQUIRED")
        if not _bibliography_matches_paper(paper, bibliography):
            raise ValueError("BIBLIOGRAPHIC_PAPER_IDENTITY_UNPROVEN")
        if not binding.evidence_integrity:
            raise ValueError("SOURCE_INTEGRITY_PROOF_REQUIRED")
        binding.validate_against_paper(paper)

        evidence_by_id = {value.evidence_id: value for value in paper.evidence}
        claims = {value.claim_id: value for value in paper.claims}
        entities = {value.entity_id: value for value in paper.entities}
        measurements = tuple(paper.measurements)
        rows: list[EvidenceMatrixRow] = []

        for record in sorted(
            paper.normalized_evidence_records, key=lambda value: value.record_id
        ):
            claim = claims.get(record.source_claim_id)
            if claim is None:
                raise ValueError("SOURCE_CLAIM_NOT_FOUND")
            anchors: list[EvidenceAnchor] = []
            for evidence_id in sorted(record.evidence_ids):
                evidence = evidence_by_id.get(evidence_id)
                proof = binding.evidence_integrity.get(evidence_id)
                anchor_id = binding.anchor_ids.get(evidence_id)
                if evidence is None or proof is None or anchor_id is None:
                    raise ValueError("SOURCE_BOUND_EVIDENCE_REQUIRED")
                expected_proof = _expected_integrity_proof(
                    evidence=evidence,
                    anchor_id=anchor_id,
                    source_hash=paper.source.content_hash,
                )
                if proof != expected_proof:
                    raise ValueError("SOURCE_INTEGRITY_PROOF_MISMATCH")
                anchors.append(
                    EvidenceAnchor(
                        anchor_id=str(anchor_id),
                        source_id=bibliography.source_id,
                        source_revision_id=str(binding.revision_id),
                        locator={
                            "paper_id": paper.paper_id,
                            "analysis_id": paper.analysis_manifest.analysis_id,
                            "evidence_id": evidence_id,
                            "char_start": proof["char_start"],
                            "char_end": proof["char_end"],
                            "section_id": proof["section_id"],
                            "evidence_type": proof["evidence_type"],
                        },
                        content_hash=proof["source_hash"],
                        excerpt_hash=proof["excerpt_hash"],
                    )
                )

            taxon_names = sorted(
                {
                    entities[entity_id].normalized_name or entities[entity_id].name
                    for entity_id in claim.subject_ids
                    if entity_id in entities and entities[entity_id].entity_type == "taxon"
                }
            )
            sample_sizes = sorted(
                {
                    measurement.sample_size
                    for measurement in measurements
                    if measurement.sample_size is not None
                    and set(measurement.evidence_ids) & set(record.evidence_ids)
                }
            )
            uncertainty = None
            if record.polarity == "uncertain":
                uncertainty = "source claim polarity is uncertain"
            elif record.review_status != "accepted":
                uncertainty = f"review status: {record.review_status}"

            row = EvidenceMatrixRow(
                evidence_id=f"matrix:{record.record_id}",
                source_id=bibliography.source_id,
                evidence_class=EvidenceClass.OBSERVATIONAL,
                anchors=tuple(anchors),
                taxon=taxon_names[0] if len(taxon_names) == 1 else None,
                outcome=claim.predicate or record.domain,
                result=record.normalized_statement,
                sample_size=(
                    ",".join(str(value) for value in sample_sizes)
                    if sample_sizes
                    else None
                ),
                uncertainty=uncertainty,
                limitations=tuple(record.validation_notes),
                metadata={
                    "paper_id": paper.paper_id,
                    "source_claim_id": claim.claim_id,
                    "normalized_record_id": record.record_id,
                    "claim_type": claim.claim_type,
                    "polarity": record.polarity,
                    "automatic_design_classification": False,
                    "original_evidence_ids": sorted(record.evidence_ids),
                },
            )
            rows.append(row)

        payload = [asdict(row) for row in rows]
        return {
            "paper_id": paper.paper_id,
            "source_id": bibliography.source_id,
            "row_count": len(rows),
            "rows": payload,
            "scientific_fields_source_bound": True,
            "automatic_design_classification": False,
            "fingerprint": hashlib.sha256(repr(payload).encode()).hexdigest(),
        }
