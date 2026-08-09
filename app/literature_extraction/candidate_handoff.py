from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any

from app.candidate_knowledge.models import (
    CandidateKind,
    EvidenceInput,
    SourceAnchor,
)
from app.candidate_knowledge.service import CandidateExtractionService

from .models import NormalizedEvidenceRecord, PaperKnowledge

DOMAIN_KINDS: dict[str, CandidateKind] = {
    "taxonomy": CandidateKind.TAXON,
    "trait": CandidateKind.TRAIT,
    "occurrence": CandidateKind.GEOGRAPHIC_OCCURRENCE,
    "habitat": CandidateKind.ECOLOGICAL_RELATIONSHIP,
    "ecological_interaction": CandidateKind.ECOLOGICAL_RELATIONSHIP,
    "conservation": CandidateKind.CONSERVATION_ASSERTION,
    "cultivation": CandidateKind.CULTIVATION_OBSERVATION,
}


@dataclass(frozen=True, slots=True)
class LiteratureSourceBinding:
    """Canonical source identities and verified literature evidence integrity.

    Canonical anchor IDs remain owned by intake/document intelligence.  Exact
    source and excerpt hashes are derived from the immutable literature ingest
    and are carried alongside those IDs so normalized text can never replace
    the original evidence locator.
    """

    source_object_type: str
    source_object_id: int
    revision_id: int
    extraction_run_id: int
    anchor_ids: dict[str, int]
    display_policy: str = "UNKNOWN_REQUIRES_REVIEW"
    internal_use_permission: bool = False
    language: str = "en"
    evidence_integrity: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_object_type.strip():
            raise ValueError("SOURCE_OBJECT_TYPE_REQUIRED")
        if min(self.source_object_id, self.revision_id, self.extraction_run_id) <= 0:
            raise ValueError("CANONICAL_SOURCE_BINDING_REQUIRED")
        if not self.anchor_ids or any(value <= 0 for value in self.anchor_ids.values()):
            raise ValueError("CANONICAL_ANCHOR_BINDINGS_REQUIRED")
        if not self.evidence_integrity:
            raise ValueError("SOURCE_INTEGRITY_PROOF_REQUIRED")

    def validate_against_paper(self, paper: Any) -> list[str]:
        known_evidence_ids = {ev.evidence_id for ev in paper.evidence}
        return [k for k in self.anchor_ids if k not in known_evidence_ids]


@dataclass(frozen=True, slots=True)
class BlockedHandoffRecord:
    record_id: str
    code: str
    details: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LiteratureCandidatePlan:
    evidence: tuple[EvidenceInput, ...]
    blocked: tuple[BlockedHandoffRecord, ...]


class LiteratureCandidateHandoffError(ValueError):
    def __init__(self, code: str, blocked: tuple[BlockedHandoffRecord, ...]) -> None:
        self.code = code
        self.blocked = blocked
        super().__init__(code)


def _subject(record: NormalizedEvidenceRecord) -> tuple[str | None, list[str]]:
    candidates = sorted(
        {*record.canonical_entity_ids, *record.unresolved_entities}
    )
    return (candidates[0] if len(candidates) == 1 else None), candidates


def _proof_matches_evidence(
    *, evidence: Any, anchor_id: int, proof: dict[str, Any], source_hash: str
) -> bool:
    return proof == {
        "anchor_id": anchor_id,
        "source_hash": source_hash,
        "excerpt_hash": sha256(evidence.excerpt.encode("utf-8")).hexdigest(),
        "char_start": evidence.span.char_start,
        "char_end": evidence.span.char_end,
        "section_id": evidence.span.section_id,
        "evidence_type": evidence.evidence_type,
    }


def build_candidate_plan(
    paper: PaperKnowledge, binding: LiteratureSourceBinding
) -> LiteratureCandidatePlan:
    """Adapt reviewed-boundary literature records without resolving ambiguity."""

    unknown_anchor_set = set(binding.validate_against_paper(paper))
    if unknown_anchor_set:
        raise ValueError(
            f"ANCHOR_EVIDENCE_IDS_NOT_IN_PAPER: {sorted(unknown_anchor_set)}"
        )

    known_evidence_ids = {item.evidence_id for item in paper.evidence}
    if set(binding.evidence_integrity) != known_evidence_ids:
        raise ValueError("SOURCE_INTEGRITY_PROOF_INCOMPLETE")

    evidence_by_id = {item.evidence_id: item for item in paper.evidence}
    claims_by_id = {item.claim_id: item for item in paper.claims}
    eligible: list[EvidenceInput] = []
    blocked: list[BlockedHandoffRecord] = []

    for record in sorted(
        paper.normalized_evidence_records, key=lambda item: item.record_id
    ):
        kind = DOMAIN_KINDS.get(record.domain)
        if kind is None:
            blocked.append(
                BlockedHandoffRecord(
                    record.record_id,
                    "UNSUPPORTED_CANDIDATE_DOMAIN",
                    {"domain": record.domain},
                )
            )
            continue

        subject, subject_candidates = _subject(record)
        if subject is None:
            blocked.append(
                BlockedHandoffRecord(
                    record.record_id,
                    "AMBIGUOUS_OR_MISSING_SUBJECT",
                    {"subject_candidates": subject_candidates},
                )
            )
            continue

        claim = claims_by_id.get(record.source_claim_id)
        if claim is None:
            blocked.append(
                BlockedHandoffRecord(
                    record.record_id,
                    "SOURCE_CLAIM_NOT_FOUND",
                    {"source_claim_id": record.source_claim_id},
                )
            )
            continue

        source_anchors: list[SourceAnchor] = []
        missing_bindings: list[str] = []
        integrity_failures: list[str] = []
        for evidence_id in sorted(record.evidence_ids):
            source_evidence = evidence_by_id.get(evidence_id)
            anchor_id = binding.anchor_ids.get(evidence_id)
            proof = binding.evidence_integrity.get(evidence_id)
            if source_evidence is None or anchor_id is None or proof is None:
                missing_bindings.append(evidence_id)
                continue
            if not _proof_matches_evidence(
                evidence=source_evidence,
                anchor_id=anchor_id,
                proof=proof,
                source_hash=paper.source.content_hash,
            ):
                integrity_failures.append(evidence_id)
                continue
            source_anchors.append(
                SourceAnchor(
                    anchor_id=anchor_id,
                    ordered_span=len(source_anchors),
                    char_start=source_evidence.span.char_start,
                    char_end=source_evidence.span.char_end,
                    block_id=source_evidence.span.section_id,
                    logical_unit=claim.claim_id,
                    locator={
                        "paper_id": paper.paper_id,
                        "analysis_id": paper.analysis_manifest.analysis_id,
                        "evidence_id": evidence_id,
                        "source_hash": proof["source_hash"],
                        "excerpt_hash": proof["excerpt_hash"],
                        "char_start": proof["char_start"],
                        "char_end": proof["char_end"],
                        "confidence": claim.provenance.confidence,
                    },
                )
            )
        if integrity_failures:
            blocked.append(
                BlockedHandoffRecord(
                    record.record_id,
                    "CANONICAL_EVIDENCE_INTEGRITY_MISMATCH",
                    {"evidence_ids": integrity_failures},
                )
            )
            continue
        if missing_bindings or not source_anchors:
            blocked.append(
                BlockedHandoffRecord(
                    record.record_id,
                    "CANONICAL_EVIDENCE_BINDING_MISSING",
                    {"evidence_ids": missing_bindings or list(record.evidence_ids)},
                )
            )
            continue

        eligible.append(
            EvidenceInput(
                source_object_type=binding.source_object_type,
                source_object_id=binding.source_object_id,
                revision_id=binding.revision_id,
                extraction_run_id=binding.extraction_run_id,
                text=record.statement,
                source_anchors=tuple(source_anchors),
                display_policy=binding.display_policy,
                internal_use_permission=binding.internal_use_permission,
                language=binding.language,
                metadata={
                    "paper_id": paper.paper_id,
                    "analysis_id": paper.analysis_manifest.analysis_id,
                    "source_hash": paper.source.content_hash,
                    "source_claim_id": claim.claim_id,
                    "source_record_id": record.record_id,
                    "source_confidence": record.extraction_confidence,
                    "normalization_confidence": record.normalization_confidence,
                    "source_evidence_integrity": {
                        evidence_id: binding.evidence_integrity[evidence_id]
                        for evidence_id in sorted(record.evidence_ids)
                        if evidence_id in binding.evidence_integrity
                    },
                    "candidate_facts": [
                        {
                            "kind": kind.value,
                            "subject": subject,
                            "predicate": claim.predicate or f"reported_{record.domain}",
                            "object_value": record.statement,
                            "qualifiers": {
                                "claim_type": claim.claim_type,
                                "polarity": claim.polarity,
                                "canonical_entity_ids": record.canonical_entity_ids,
                                "unresolved_entities": record.unresolved_entities,
                                "validation_notes": record.validation_notes,
                            },
                            "confidence": min(
                                record.extraction_confidence,
                                record.normalization_confidence,
                            ),
                            "method": "LITERATURE_NORMALIZED_EVIDENCE_ADAPTER",
                        }
                    ],
                },
            )
        )

    return LiteratureCandidatePlan(tuple(eligible), tuple(blocked))


class LiteratureCandidateHandoffService:
    def __init__(
        self,
        candidate_service: CandidateExtractionService,
        candidate_repository: Any,
    ) -> None:
        self.candidate_service = candidate_service
        self.candidate_repository = candidate_repository

    def handoff(
        self, paper: PaperKnowledge, binding: LiteratureSourceBinding
    ) -> dict[str, Any]:
        plan = build_candidate_plan(paper, binding)
        if not plan.evidence:
            raise LiteratureCandidateHandoffError("NO_ELIGIBLE_CANDIDATES", plan.blocked)
        preview = self.candidate_service.preview(
            list(plan.evidence),
            {
                "adapter": "calyx-syn-002",
                "paper_id": paper.paper_id,
                "analysis_id": paper.analysis_manifest.analysis_id,
                "configuration_fingerprint": paper.analysis_manifest.configuration_fingerprint,
            },
        )
        result = self.candidate_service.execute(preview["candidate_run_id"])
        candidate_ids = sorted(
            candidate["candidate_id"]
            for candidate in self.candidate_repository.candidates_for_run(
                preview["candidate_run_id"]
            )
        )
        return {
            "paper_id": paper.paper_id,
            "analysis_id": paper.analysis_manifest.analysis_id,
            "candidate_run_id": preview["candidate_run_id"],
            "state": result["state"],
            "plan_counts": preview["counts"],
            "candidate_ids": candidate_ids,
            "blocked_records": [asdict(item) for item in plan.blocked],
            "published": False,
            "review_required": True,
            "exact_source_integrity": True,
        }
