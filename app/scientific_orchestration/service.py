from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, ClassVar

from app.evidence_aggregation.models import CandidateInput


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


class RiskClass(StrEnum):
    LEVEL_0_DETERMINISTIC_METADATA = "LEVEL_0_DETERMINISTIC_METADATA"
    LEVEL_1_ROUTINE_SCIENTIFIC = "LEVEL_1_ROUTINE_SCIENTIFIC"
    LEVEL_2_SCIENTIFIC_INFERENCE = "LEVEL_2_SCIENTIFIC_INFERENCE"
    LEVEL_3_CONFLICTING_OR_AMBIGUOUS = "LEVEL_3_CONFLICTING_OR_AMBIGUOUS"
    LEVEL_4_HIGH_IMPACT = "LEVEL_4_HIGH_IMPACT"


class RoutingOutcome(StrEnum):
    PROVISIONAL_KNOWLEDGE = "PROVISIONAL_KNOWLEDGE"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    EXPERT_REVIEW_REQUIRED = "EXPERT_REVIEW_REQUIRED"
    PUBLICATION_REVIEW_REQUIRED = "PUBLICATION_REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"


class ScientificOrchestrationError(ValueError):
    def __init__(self, code: str, details: dict[str, Any] | None = None) -> None:
        self.code = code
        self.details = details or {}
        super().__init__(code)


class MemoryScientificOrchestrationRepository:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []

    def get(self, orchestration_id: str) -> dict[str, Any] | None:
        record = self.records.get(orchestration_id)
        return deepcopy(record) if record else None

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self.records[record["orchestration_id"]] = deepcopy(record)
        return deepcopy(record)

    def append_event(
        self, orchestration_id: str, event_type: str, details: dict[str, Any]
    ) -> None:
        self.events.append(
            {
                "event_id": len(self.events) + 1,
                "orchestration_id": orchestration_id,
                "event_type": event_type,
                "details": deepcopy(details),
                "created_at": _now(),
            }
        )

    def history(self, orchestration_id: str) -> list[dict[str, Any]]:
        return [
            deepcopy(item)
            for item in self.events
            if item["orchestration_id"] == orchestration_id
        ]


class GovernedScientificOrchestrationService:
    """Risk-based orchestration that governs promotion rather than processing."""

    HIGH_IMPACT_KINDS: ClassVar[set[str]] = {
        "CONSERVATION_ASSERTION",
        "CONSERVATION_ACTION",
        "TAXON_NAME_USAGE",
    }
    SCIENTIFIC_INFERENCE_KINDS: ClassVar[set[str]] = {
        "MECHANISTIC_RELATIONSHIP",
    }

    def __init__(
        self,
        *,
        candidate_repository: Any,
        aggregation_service: Any,
        aggregation_repository: Any,
        interpretation_service: Any,
        interpretation_repository: Any,
        repository: MemoryScientificOrchestrationRepository | None = None,
        policy_version: str = "calyx-brain-001c-risk-1",
    ) -> None:
        self.candidates = candidate_repository
        self.aggregation = aggregation_service
        self.aggregates = aggregation_repository
        self.interpretation = interpretation_service
        self.interpretations = interpretation_repository
        self.repository = repository or MemoryScientificOrchestrationRepository()
        self.policy_version = policy_version

    def _processable_candidates(self, candidate_run_id: int) -> list[dict[str, Any]]:
        candidates = self.candidates.candidates_for_run(candidate_run_id)
        if not candidates:
            raise ScientificOrchestrationError("CANDIDATE_RUN_EMPTY")
        accepted: list[dict[str, Any]] = []
        rejected: list[int] = []
        for candidate in candidates:
            if candidate.get("review_state") == "REJECTED":
                rejected.append(candidate["candidate_id"])
                continue
            accepted.append(candidate)
        if not accepted:
            raise ScientificOrchestrationError(
                "NO_PROCESSABLE_CANDIDATES", {"rejected_candidate_ids": rejected}
            )
        return accepted

    def _candidate_to_aggregate_input(self, candidate: dict[str, Any]) -> CandidateInput:
        anchors = tuple(
            int(anchor["anchor_id"])
            for anchor in candidate.get("source_anchors", [])
            if anchor.get("anchor_id") is not None
        )
        return CandidateInput(
            candidate_id=int(candidate["candidate_id"]),
            candidate_version=int(candidate.get("version", 1)),
            candidate_type=str(candidate["kind"]),
            normalized_subject=str(candidate["normalized_subject"]),
            predicate=str(candidate["predicate"]),
            object_value=candidate.get("object_value"),
            numeric_value=candidate.get("numeric_value"),
            unit=candidate.get("unit"),
            source_revision_id=int(candidate["revision_id"]),
            source_document_id=str(candidate.get("source_object_id", "")),
            source_anchor_ids=anchors,
            evidence_type=str(candidate.get("evidence_type", "UNKNOWN")),
            source_class=str(candidate.get("source_class", "UNKNOWN")),
            directness=str(candidate.get("directness", "INDIRECT")),
            source_lineage=candidate.get("source_lineage"),
            citation_lineage=tuple(candidate.get("citation_lineage") or ()),
            document_hash=candidate.get("document_hash"),
            taxon_links=tuple(candidate.get("taxon_links") or ()),
            temporal_context=deepcopy(candidate.get("temporal_context") or {}),
            geographic_context=deepcopy(candidate.get("geographic_context") or {}),
            method_context=deepcopy(candidate.get("method_context") or {}),
            population_context=deepcopy(candidate.get("population_context") or {}),
            measurement_context=deepcopy(candidate.get("measurement_context") or {}),
            confidence=float(candidate.get("confidence", 0.5)),
            review_state=str(candidate.get("review_state", "REQUIRED")),
            verification_state=str(candidate.get("verification_state", "UNVERIFIED")),
            status=str(candidate.get("status", "ACTIVE")),
            display_policy=str(candidate.get("display_policy", "UNKNOWN_REQUIRES_REVIEW")),
            metadata=deepcopy(candidate.get("metadata") or {}),
        )

    def _risk_class(self, candidates: list[dict[str, Any]]) -> RiskClass:
        kinds = {str(item.get("kind")) for item in candidates}
        if kinds & self.HIGH_IMPACT_KINDS:
            return RiskClass.LEVEL_4_HIGH_IMPACT
        if any(item.get("conflict_state") == "OPEN" for item in candidates):
            return RiskClass.LEVEL_3_CONFLICTING_OR_AMBIGUOUS
        if kinds & self.SCIENTIFIC_INFERENCE_KINDS:
            return RiskClass.LEVEL_2_SCIENTIFIC_INFERENCE
        if kinds <= {"DOCUMENT_METADATA", "TAXON_NAME_USAGE"}:
            return RiskClass.LEVEL_0_DETERMINISTIC_METADATA
        return RiskClass.LEVEL_1_ROUTINE_SCIENTIFIC

    def _routing_outcome(self, risk_class: RiskClass) -> RoutingOutcome:
        if risk_class == RiskClass.LEVEL_0_DETERMINISTIC_METADATA:
            return RoutingOutcome.PROVISIONAL_KNOWLEDGE
        if risk_class == RiskClass.LEVEL_1_ROUTINE_SCIENTIFIC:
            return RoutingOutcome.HUMAN_REVIEW_REQUIRED
        if risk_class == RiskClass.LEVEL_2_SCIENTIFIC_INFERENCE:
            return RoutingOutcome.EXPERT_REVIEW_REQUIRED
        if risk_class == RiskClass.LEVEL_3_CONFLICTING_OR_AMBIGUOUS:
            return RoutingOutcome.BLOCKED
        return RoutingOutcome.PUBLICATION_REVIEW_REQUIRED

    def preview(self, candidate_run_id: int) -> dict[str, Any]:
        candidates = self._processable_candidates(candidate_run_id)
        risk_class = self._risk_class(candidates)
        aggregate_inputs = [self._candidate_to_aggregate_input(item) for item in candidates]
        aggregate_preview = self.aggregation.preview(aggregate_inputs)
        orchestration_id = _fingerprint(
            {
                "candidate_run_id": candidate_run_id,
                "candidate_ids": sorted(item["candidate_id"] for item in candidates),
                "aggregate_run_id": aggregate_preview["aggregate_run_id"],
                "policy_version": self.policy_version,
            }
        )[:24]
        record = {
            "orchestration_id": orchestration_id,
            "candidate_run_id": candidate_run_id,
            "candidate_ids": sorted(item["candidate_id"] for item in candidates),
            "aggregate_run_id": aggregate_preview["aggregate_run_id"],
            "risk_class": risk_class.value,
            "routing_outcome": self._routing_outcome(risk_class).value,
            "policy_version": self.policy_version,
            "state": "PLANNED",
            "published": False,
            "automatic_publication": False,
            "canonical_graph_mutation": False,
            "created_at": _now(),
        }
        self.repository.save(record)
        self.repository.append_event(orchestration_id, "PREVIEWED", record)
        return deepcopy(record)

    def execute(self, orchestration_id: str) -> dict[str, Any]:
        record = self.repository.get(orchestration_id)
        if record is None:
            raise ScientificOrchestrationError("ORCHESTRATION_NOT_FOUND")
        if record["state"] == "COMPLETED":
            return record
        aggregate_result = self.aggregation.execute(record["aggregate_run_id"])
        record["aggregate_state"] = aggregate_result["state"]
        if aggregate_result["state"] != "COMPLETED":
            record["state"] = "PARTIAL"
            self.repository.save(record)
            self.repository.append_event(orchestration_id, "PARTIAL", record)
            return deepcopy(record)
        record["state"] = "COMPLETED"
        self.repository.save(record)
        self.repository.append_event(orchestration_id, "COMPLETED", record)
        return deepcopy(record)
