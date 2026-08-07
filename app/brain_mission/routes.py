from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.candidate_knowledge.models import EvidenceInput, SourceAnchor
from app.candidate_knowledge.repository import MemoryCandidateRepository
from app.candidate_knowledge.service import CandidateExtractionService
from app.evidence_aggregation.models import CandidateInput
from app.evidence_aggregation.repository import MemoryAggregateRepository
from app.evidence_aggregation.service import EvidenceAggregationService
from app.evidence_retrieval.models import RetrievalQuery
from app.evidence_retrieval.routes import ENGINE
from app.reasoning_ledger import gate as publication_gate
from app.reasoning_ledger.models import (
    LedgerEntry,
    LedgerEntryKind,
    LedgerProvenance,
    UncertaintyMarker,
)
from app.reasoning_ledger.service import InMemoryReasoningLedgerService
from app.scientific_interpretation.models import (
    CONTEXT_DIMENSIONS,
    CompletenessState,
    ContextForm,
    InterpretationRequest,
    SourceAnchorReference,
    SourceEvidenceReference,
)
from app.scientific_interpretation.repository import MemoryInterpretationRepository
from app.scientific_interpretation.service import ScientificInterpretationService

from .service import BrainMissionService, MemoryMissionRepository, MissionComponents


class MissionStartIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    project_id: str = Field(min_length=1, max_length=200)
    tenant_id: str = Field(default="brain", min_length=1, max_length=200)
    actor: str = Field(default="brain-operator", min_length=1, max_length=200)
    max_sources: int = Field(default=20, ge=1, le=100)
    max_execution_steps: int = Field(default=10, ge=1, le=10)
    timeout_seconds: float = Field(default=30, ge=0.1, le=300)


def _retrieve(context: dict[str, Any]) -> dict[str, Any]:
    results_by_id: dict[str, dict[str, Any]] = {}
    source_budget = int(context["limits"]["max_sources"])
    per_query = max(1, int(context["plan"]["per_domain_source_budget"]))
    for query in context["plan"]["retrieval_queries"]:
        if len(results_by_id) >= source_budget:
            break
        response = ENGINE.search(
            RetrievalQuery(
                text=query,
                mode="HYBRID",
                limit=min(per_query, source_budget - len(results_by_id)),
                per_source_limit=2,
                parent_expansion="NONE",
                internal_access=False,
            )
        )
        for result in response["results"]:
            results_by_id.setdefault(str(result["result_id"]), result)
            if len(results_by_id) >= source_budget:
                break
    return {"results": list(results_by_id.values())}


class ExistingBrainMissionAdapter:
    """Lossless adapters over current evidence, interpretation, and ledger services."""

    def __init__(self) -> None:
        self.candidate_repository = MemoryCandidateRepository()
        self.candidates = CandidateExtractionService(self.candidate_repository)
        self.aggregate_repository = MemoryAggregateRepository()
        self.aggregation = EvidenceAggregationService(self.aggregate_repository)
        self.interpretation_repository = MemoryInterpretationRepository()
        self.interpretation = ScientificInterpretationService(
            self.interpretation_repository
        )
        self.ledgers = InMemoryReasoningLedgerService()

    @staticmethod
    def _canonical_document(result: dict[str, Any]) -> dict[str, Any]:
        citation = result.get("citation") or {}
        revision_id = citation.get("revision_id")
        anchor_ids = tuple(citation.get("source_anchor_ids") or ())
        locator = citation.get("locator")
        if not isinstance(revision_id, int) or revision_id <= 0:
            raise ValueError("CANONICAL_REVISION_ID_REQUIRED")
        if not anchor_ids or any(not isinstance(value, int) or value <= 0 for value in anchor_ids):
            raise ValueError("EXACT_SOURCE_ANCHORS_REQUIRED")
        if not isinstance(locator, dict) or not locator:
            raise ValueError("EXACT_SOURCE_LOCATOR_REQUIRED")
        object_type = str(result.get("object_type") or "").strip()
        matches = [
            document
            for document in ENGINE.repo.documents
            if document.get("active", False)
            and document.get("source_object_type") == object_type
            and document.get("revision_id") == revision_id
            and tuple(document.get("anchors") or ()) == anchor_ids
        ]
        if not matches:
            raise ValueError("CANONICAL_SOURCE_IDENTITY_NOT_FOUND")
        if len(matches) != 1:
            raise ValueError("AMBIGUOUS_CANONICAL_SOURCE_IDENTITY")
        document = matches[0]
        for field in ("source_object_id", "revision_id", "extraction_run_id"):
            if not isinstance(document.get(field), int) or document[field] <= 0:
                raise ValueError("INVALID_CANONICAL_SOURCE_IDENTITY")
        return document

    @classmethod
    def _canonical_source(cls, result: dict[str, Any]) -> EvidenceInput:
        document = cls._canonical_document(result)
        citation = result["citation"]
        text = result.get("authorized_excerpt")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("AUTHORIZED_EVIDENCE_SPAN_REQUIRED")
        locator = dict(citation["locator"])
        metadata = dict(document.get("metadata") or {})
        metadata.update(
            source_confidence=float(result.get("fused_score", 0.5)),
            content_hash=document.get("content_hash"),
        )
        return EvidenceInput(
            source_object_type=str(document["source_object_type"]),
            source_object_id=document["source_object_id"],
            revision_id=document["revision_id"],
            extraction_run_id=document["extraction_run_id"],
            text=text,
            source_anchors=tuple(
                SourceAnchor(
                    anchor_id=value,
                    ordered_span=index,
                    locator=locator,
                )
                for index, value in enumerate(document.get("anchors") or ())
            ),
            display_policy=str(
                result.get("display_policy") or "UNKNOWN_REQUIRES_REVIEW"
            ),
            internal_use_permission=False,
            metadata=metadata,
        )

    def aggregate(self, context: dict[str, Any]) -> dict[str, Any]:
        translated: list[EvidenceInput] = []
        gaps: list[dict[str, Any]] = []
        for result in context["sources"]:
            try:
                translated.append(self._canonical_source(result))
            except ValueError as exc:
                gaps.append(
                    {"source_id": result.get("result_id"), "reason": str(exc)}
                )
        if not translated:
            raise ValueError("NO_CANONICAL_RETRIEVAL_EVIDENCE")

        candidate_plan = self.candidates.preview(
            translated, {"mission_id": context["mission_id"]}
        )
        candidate_status = self.candidates.execute(candidate_plan["candidate_run_id"])
        candidates = self.candidate_repository.candidates_for_run(
            candidate_plan["candidate_run_id"]
        )
        if not candidates:
            raise ValueError("NO_CANDIDATE_KNOWLEDGE_EXTRACTED")

        conflict_pairs = {
            tuple(sorted(group["candidate_ids"]))
            for group in self.candidate_repository.conflicts.values()
        }
        inputs: list[CandidateInput] = []
        for candidate in candidates:
            links = [
                item
                for item in self.candidate_repository.evidence_links
                if item["candidate_id"] == candidate["candidate_id"]
            ]
            if not links:
                raise ValueError("CANDIDATE_EVIDENCE_LINK_REQUIRED")
            evidence = next(
                (
                    item
                    for item in translated
                    if item.revision_id == links[0]["revision_id"]
                    and item.source_object_id == links[0]["source_object_id"]
                ),
                None,
            )
            if evidence is None:
                raise ValueError("CANDIDATE_SOURCE_RECONSTRUCTION_FAILED")
            relationship_to = {
                str(other): "CONTRADICTS"
                for pair in conflict_pairs
                if candidate["candidate_id"] in pair
                for other in pair
                if other != candidate["candidate_id"]
            }
            taxon_identity = evidence.metadata.get("taxon_identity")
            taxon_links = (
                (dict(taxon_identity),) if isinstance(taxon_identity, dict) else ()
            )
            inputs.append(
                CandidateInput(
                    candidate_id=candidate["candidate_id"],
                    candidate_version=candidate["version"],
                    candidate_type=candidate["kind"],
                    normalized_subject=candidate["normalized_subject"],
                    predicate=candidate["predicate"],
                    object_value=candidate.get("object_value"),
                    numeric_value=candidate.get("numeric_value"),
                    unit=candidate.get("unit"),
                    source_revision_id=evidence.revision_id,
                    source_document_id=(
                        f"{evidence.source_object_type}:{evidence.source_object_id}"
                    ),
                    source_anchor_ids=tuple(
                        item["anchor"]["anchor_id"] for item in links
                    ),
                    evidence_type=str(
                        evidence.metadata.get("claim_role") or "CLAIM"
                    ),
                    source_class=str(
                        evidence.metadata.get("source_class") or "UNKNOWN"
                    ),
                    directness=str(
                        evidence.metadata.get("directness") or "INDIRECT"
                    ),
                    document_hash=evidence.metadata.get("content_hash"),
                    taxon_links=taxon_links,
                    confidence=float(candidate["confidence"]),
                    review_state=str(candidate["review_state"]),
                    verification_state="UNVERIFIED",
                    display_policy=evidence.display_policy,
                    metadata={
                        "source_name": evidence.metadata.get("taxon")
                        or candidate["normalized_subject"],
                        "relationship_to": relationship_to,
                        "provenance": evidence.metadata.get("provenance", {}),
                        "claim_role": evidence.metadata.get("claim_role", "CLAIM"),
                    },
                )
            )

        aggregate_plan = self.aggregation.preview(inputs)
        aggregate_status = self.aggregation.execute(aggregate_plan["aggregate_run_id"])
        candidate_ids = {item.candidate_id for item in inputs}
        aggregates = [
            item
            for item in self.aggregate_repository.aggregates
            if set(item["contributing_candidate_ids"]).issubset(candidate_ids)
        ]
        evidence_records = [
            {
                "type": "claim",
                "candidate_id": item.candidate_id,
                "candidate_version": item.candidate_version,
                "subject": item.normalized_subject,
                "predicate": item.predicate,
                "value": (
                    item.object_value
                    if item.object_value is not None
                    else item.numeric_value
                ),
                "source_revision_id": item.source_revision_id,
                "source_anchor_ids": list(item.source_anchor_ids),
                "provenance": item.metadata.get("provenance", {}),
            }
            for item in inputs
        ]
        contradictory_ids = {value for pair in conflict_pairs for value in pair}
        return {
            "supporting_evidence": [
                item
                for item in evidence_records
                if item["candidate_id"] not in contradictory_ids
            ],
            "contradicting_evidence": [
                item
                for item in evidence_records
                if item["candidate_id"] in contradictory_ids
            ],
            "artifacts": {
                "candidate_run_id": candidate_plan["candidate_run_id"],
                "candidate_status": candidate_status["state"],
                "canonical_evidence": [asdict(item) for item in translated],
                "translation_gaps": gaps,
                "aggregate_run_id": aggregate_plan["aggregate_run_id"],
                "aggregate_status": aggregate_status["state"],
                "aggregate_version_ids": [
                    item["aggregate_version_id"] for item in aggregates
                ],
                "aggregate_records": aggregates,
                "candidate_confidences": {
                    str(item.candidate_id): item.confidence for item in inputs
                },
            },
        }

    @staticmethod
    def analyze(context: dict[str, Any]) -> dict[str, Any]:
        records = context["artifacts"].get("aggregate_records", [])
        covered = {
            "taxonomy"
            if item["candidate_type"] == "TAXON"
            else "geographic_distribution"
            if item["candidate_type"] == "GEOGRAPHIC_OCCURRENCE"
            else "conservation"
            if item["candidate_type"] == "CONSERVATION_ASSERTION"
            else "pollination_biology"
            if "pollinat" in item["normalized_predicate"]
            else "mycorrhiza"
            if "mycorrh" in item["normalized_predicate"]
            else "other"
            for item in records
        }
        missing = [
            domain for domain in context["plan"]["domains"] if domain not in covered
        ]
        missing.extend(
            f"source {item.get('source_id')}: {item['reason']}"
            for item in context["artifacts"].get("translation_gaps", [])
        )
        return {
            "contradicting_evidence": context["contradicting_evidence"],
            "missing_evidence": missing,
        }

    def interpret(self, context: dict[str, Any]) -> dict[str, Any]:
        sources: list[SourceEvidenceReference] = []
        for value in context["artifacts"]["canonical_evidence"]:
            anchors = tuple(
                SourceAnchorReference(
                    anchor_id=item["anchor_id"],
                    order=item["ordered_span"],
                    anchor_type="TEXT_SPAN",
                    locator=item["locator"],
                    content_hash=(
                        value["metadata"].get("content_hash")
                        or hashlib.sha256(value["text"].encode()).hexdigest()
                    ),
                    relationship="EVIDENCE",
                )
                for item in value["source_anchors"]
            )
            sources.append(
                SourceEvidenceReference(
                    source_object_type=value["source_object_type"],
                    source_object_id=value["source_object_id"],
                    source_revision_id=value["revision_id"],
                    publication_metadata={},
                    copyright_policy=value["display_policy"],
                    provenance=(
                        value["metadata"].get("provenance")
                        or {"extraction_run_id": value["extraction_run_id"]}
                    ),
                    anchors=anchors,
                )
            )

        dimensions = {
            name: (
                CompletenessState.PRESENT
                if name in {"citations", "biological_context"}
                else CompletenessState.UNKNOWN
            )
            for name in CONTEXT_DIMENSIONS
        }
        packet = self.interpretation.construct_packet(
            packet_key=f"brain-mission:{context['mission_id']}",
            context_form=ContextForm.SEMANTIC_CONTEXT,
            sources=tuple(sources),
            context_dimensions=dimensions,
            material_dimensions=("citations", "biological_context"),
            structural_relationships=(),
            construction_policy_version="brain-mission-current-1",
            boundary_analyzer_version="brain-mission-current-1",
            construction_rationale=(
                "Immutable source identities, exact anchors, authorized spans, "
                "candidate claims, conflicts, and known gaps retained."
            ),
        )
        confidences = list(context["artifacts"]["candidate_confidences"].values())
        confidence = min(confidences) if confidences else 0.0
        conclusion = {
            "type": "inference",
            "text": (
                "The bounded evidence set supports a provisional synthesis "
                "requiring human scientific review."
            ),
            "claim_ids": sorted(context["artifacts"]["candidate_confidences"]),
        }
        interpreted = self.interpretation.interpret(
            InterpretationRequest(
                packet_ids=(packet["packet_id"],),
                interpretation_key=(
                    f"brain-mission:{context['mission_id']}:synthesis"
                ),
                statement={
                    "question": context["question"],
                    "conclusion": conclusion,
                    "missing_evidence": context["missing_evidence"],
                },
                reasoning={
                    "rule": "bounded evidence reconciliation",
                    "claims_remain_external": True,
                    "private_chain_of_thought": False,
                },
                confidence_factors={
                    "minimum_candidate_confidence": confidence,
                    "provenance": 1.0,
                },
                ambiguities=tuple(
                    {"missing_domain": item} for item in context["missing_evidence"]
                ),
                alternatives=tuple(
                    {"contradicting_candidate_id": item["candidate_id"]}
                    for item in context["contradicting_evidence"]
                ),
                configuration={"max_sources": context["limits"]["max_sources"]},
            )
        )
        return {
            "confidence": confidence,
            "conclusions": [conclusion],
            "artifacts": {
                "evidence_packet_id": packet["packet_id"],
                "interpretation_id": interpreted["interpretation_id"],
            },
        }

    def create_ledger(self, context: dict[str, Any]) -> dict[str, Any]:
        ledger = self.ledgers.create(
            tenant_id=context["tenant_id"],
            project_id=context["project_id"],
            title=f"Brain mission {context['mission_id']}",
            description=context["question"],
            created_by=context["actor"],
        )
        confidence = float(context.get("confidence") or 0.0)
        records = [
            (
                LedgerEntryKind.OBJECTIVE,
                context["question"],
                1.0,
                {"artifact_type": "question"},
            ),
            *[
                (
                    LedgerEntryKind.SUPPORT,
                    json.dumps(item, sort_keys=True),
                    confidence,
                    {"artifact_type": "source_claim"},
                )
                for item in context["supporting_evidence"]
            ],
            *[
                (
                    LedgerEntryKind.COUNTEREVIDENCE,
                    json.dumps(item, sort_keys=True),
                    confidence,
                    {"artifact_type": "contradicting_claim"},
                )
                for item in context["contradicting_evidence"]
            ],
            *[
                (
                    LedgerEntryKind.CONCLUSION,
                    item["text"],
                    confidence,
                    {
                        "artifact_type": "scientific_inference",
                        "claim_ids": item["claim_ids"],
                    },
                )
                for item in context["conclusions"]
            ],
        ]
        for index, (kind, text, entry_confidence, attributes) in enumerate(records):
            ledger = self.ledgers.append(
                str(ledger.ledger_id),
                LedgerEntry(
                    entry_id=uuid5(
                        NAMESPACE_URL,
                        f"{context['mission_id']}:{kind.value}:{index}",
                    ),
                    kind=kind,
                    text=text,
                    author=context["actor"],
                    tenant_id=context["tenant_id"],
                    project_id=context["project_id"],
                    provenance=LedgerProvenance(
                        source_kind="brain_mission",
                        source_id=context["mission_id"],
                        rs_project_id=context["project_id"],
                        execution_id=context["mission_id"],
                        retrieved_at=datetime.now(timezone.utc),
                        collector=context["actor"],
                        extra={
                            "interpretation_id": context["artifacts"][
                                "interpretation_id"
                            ]
                        },
                    ),
                    uncertainty=UncertaintyMarker(
                        confidence=entry_confidence,
                        rationale="Bounded minimum evidence confidence.",
                    ),
                    attributes={
                        **attributes,
                        "private_chain_of_thought": False,
                        "automatically_published": False,
                    },
                ),
                actor=context["actor"],
                tenant_id=context["tenant_id"],
            )
        return {"ledger_id": str(ledger.ledger_id), "version": ledger.version}

    def validate(self, context: dict[str, Any]) -> dict[str, Any]:
        ledger = self.ledgers.current(
            context["reasoning_ledger"]["ledger_id"],
            tenant_id=context["tenant_id"],
        )
        violations = publication_gate.evaluate(ledger)
        structural = [
            violation.code
            for violation in violations
            if violation.code != "MISSING_HUMAN_APPROVAL"
        ]
        return {
            "valid": not structural,
            "blockers": structural,
            "artifacts": {
                "publication_gate_blockers": [
                    violation.code for violation in violations
                ]
            },
        }

    @staticmethod
    def review_state(context: dict[str, Any]) -> dict[str, Any]:
        return {"status": "HUMAN_REVIEW_REQUIRED"}

    def publication_eligibility(self, context: dict[str, Any]) -> dict[str, Any]:
        ledger = self.ledgers.current(
            context["reasoning_ledger"]["ledger_id"],
            tenant_id=context["tenant_id"],
        )
        blockers = [violation.code for violation in publication_gate.evaluate(ledger)]
        return {
            "eligible": not blockers,
            "blockers": blockers or ["HUMAN_REVIEW_REQUIRED"],
        }


REPOSITORY = MemoryMissionRepository()
ADAPTER = ExistingBrainMissionAdapter()
SERVICE = BrainMissionService(
    MissionComponents(
        retrieve=_retrieve,
        aggregate=ADAPTER.aggregate,
        analyze=ADAPTER.analyze,
        interpret=ADAPTER.interpret,
        create_ledger=ADAPTER.create_ledger,
        validate=ADAPTER.validate,
        review_state=ADAPTER.review_state,
        publication_eligibility=ADAPTER.publication_eligibility,
    ),
    REPOSITORY,
)
router = APIRouter(prefix="/missions", tags=["brain-scientific-missions"])


@router.post("", status_code=201)
def start_mission(payload: MissionStartIn) -> dict[str, Any]:
    try:
        return SERVICE.start(
            question=payload.question,
            tenant_id=payload.tenant_id,
            project_id=payload.project_id,
            actor=payload.actor,
            max_sources=payload.max_sources,
            max_steps=payload.max_execution_steps,
            timeout_seconds=payload.timeout_seconds,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, detail={"code": str(exc)}) from exc


@router.get("/{mission_id}")
def get_mission(mission_id: str) -> dict[str, Any]:
    try:
        return SERVICE.status(mission_id)
    except LookupError as exc:
        raise HTTPException(404, detail={"code": "MISSION_NOT_FOUND"}) from exc
