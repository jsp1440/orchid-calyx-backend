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
            if candidate.get("published"):
                raise ScientificOrchestrationError(
                    "CANDIDATE_ALREADY_PUBLISHED",
                    {"candidate_id": candidate["candidate_id"]},
                )
            accepted.append(candidate)
        if not accepted:
            raise ScientificOrchestrationError(
                "ALL_CANDIDATES_REJECTED", {"candidate_ids": rejected}
            )
        return accepted

    def _candidate_input(self, candidate: dict[str, Any]) -> CandidateInput:
        links = [
            item
            for item in self.candidates.evidence_links
            if item["candidate_id"] == candidate["candidate_id"]
        ]
        if not links:
            raise ScientificOrchestrationError(
                "INCOMPLETE_EVIDENCE", {"candidate_id": candidate["candidate_id"]}
            )
        revision_ids = {item["revision_id"] for item in links}
        if len(revision_ids) != 1:
            raise ScientificOrchestrationError(
                "STALE_OR_CONFLICTING_REVISION",
                {"candidate_id": candidate["candidate_id"]},
            )
        return CandidateInput(
            candidate_id=candidate["candidate_id"],
            candidate_version=candidate["version"],
            candidate_type=candidate["kind"],
            normalized_subject=candidate["normalized_subject"],
            predicate=candidate["predicate"],
            object_value=candidate.get("object_value"),
            numeric_value=candidate.get("numeric_value"),
            unit=candidate.get("unit"),
            source_revision_id=next(iter(revision_ids)),
            source_document_id=str(links[0].get("source_object_id") or ""),
            source_anchor_ids=tuple(
                sorted(item["anchor"]["anchor_id"] for item in links)
            ),
            evidence_type=str(candidate.get("method") or "LITERATURE"),
            source_class="PRIMARY",
            directness="DIRECT_OBSERVATION",
            document_hash=links[0]["anchor"].get("locator", {}).get("source_hash"),
            confidence=float(candidate.get("confidence", 0.5)),
            review_state=str(candidate.get("review_state") or "REQUIRED"),
            display_policy=str(
                links[0].get("display_policy") or "UNKNOWN_REQUIRES_REVIEW"
            ),
            metadata={
                "candidate": deepcopy(candidate),
                "evidence_links": deepcopy(links),
            },
        )

    def _risk_class(
        self, candidates: list[dict[str, Any]], aggregates: list[dict[str, Any]]
    ) -> RiskClass:
        if any(
            candidate.get("kind") in self.HIGH_IMPACT_KINDS for candidate in candidates
        ):
            return RiskClass.LEVEL_4_HIGH_IMPACT
        if any(
            aggregate.get("contradictory_evidence_count", 0) > 0
            or aggregate.get("unresolved_evidence_count", 0) > 0
            or aggregate.get("uncertainty_dimensions", {}).get("taxon_ambiguity", 0) > 0
            for aggregate in aggregates
        ):
            return RiskClass.LEVEL_3_CONFLICTING_OR_AMBIGUOUS
        if any(
            candidate.get("kind") in self.SCIENTIFIC_INFERENCE_KINDS
            for candidate in candidates
        ):
            return RiskClass.LEVEL_2_SCIENTIFIC_INFERENCE
        minimum_confidence = min(
            float(item.get("confidence", 0.5)) for item in candidates
        )
        if minimum_confidence < 0.6:
            return RiskClass.LEVEL_2_SCIENTIFIC_INFERENCE
        if all(
            item.get("kind") in {"SPECIMEN_REFERENCE", "OCCURRENCE"}
            for item in candidates
        ):
            return RiskClass.LEVEL_0_DETERMINISTIC_METADATA
        return RiskClass.LEVEL_1_ROUTINE_SCIENTIFIC

    def _route(
        self, risk_class: RiskClass, *, publication_requested: bool
    ) -> RoutingOutcome:
        if publication_requested:
            return RoutingOutcome.PUBLICATION_REVIEW_REQUIRED
        if risk_class in {
            RiskClass.LEVEL_0_DETERMINISTIC_METADATA,
            RiskClass.LEVEL_1_ROUTINE_SCIENTIFIC,
        }:
            return RoutingOutcome.PROVISIONAL_KNOWLEDGE
        if risk_class is RiskClass.LEVEL_2_SCIENTIFIC_INFERENCE:
            return RoutingOutcome.HUMAN_REVIEW_REQUIRED
        return RoutingOutcome.EXPERT_REVIEW_REQUIRED

    def continue_run(
        self, candidate_run_id: int, *, publication_requested: bool = False
    ) -> dict[str, Any]:
        candidates = self._processable_candidates(candidate_run_id)
        signature = {
            "candidate_run_id": candidate_run_id,
            "candidate_versions": sorted(
                f"{item['candidate_id']}:{item['version']}" for item in candidates
            ),
            "policy_version": self.policy_version,
            "publication_requested": publication_requested,
        }
        orchestration_id = _fingerprint(signature)
        existing = self.repository.get(orchestration_id)
        if existing and existing["state"] in {
            "PROVISIONAL_SCIENTIFIC_RECORD",
            "REVIEW_ROUTED",
            "PUBLICATION_REVIEW_REQUIRED",
        }:
            existing["reused"] = True
            existing["history"] = self.repository.history(orchestration_id)
            return existing

        record = existing or {
            "orchestration_id": orchestration_id,
            "candidate_run_id": candidate_run_id,
            "candidate_ids": sorted(item["candidate_id"] for item in candidates),
            "state": "MACHINE_VALIDATED",
            "lifecycle_state": "MACHINE_VALIDATED",
            "published": False,
            "provisional": True,
            "publication_status": "NOT_PUBLISHED",
            "blockers": [],
            "downstream": {},
            "policy_version": self.policy_version,
            "created_at": _now(),
        }
        if not existing:
            self.repository.append_event(
                orchestration_id, "CANDIDATES_MACHINE_VALIDATED", signature
            )

        candidate_inputs = [self._candidate_input(item) for item in candidates]
        preview = self.aggregation.preview(candidate_inputs)
        self.aggregation.execute(preview["aggregate_run_id"])
        candidate_ids = set(record["candidate_ids"])
        aggregates = [
            item
            for item in self.aggregates.aggregates
            if item.get("aggregate_version_id")
            and set(item.get("contributing_candidate_ids", ())).issubset(candidate_ids)
        ]
        if not aggregates:
            raise ScientificOrchestrationError("AGGREGATION_RESULT_MISSING")

        record["downstream"]["aggregate_run_id"] = preview["aggregate_run_id"]
        record["downstream"]["aggregate_version_ids"] = sorted(
            item["aggregate_version_id"] for item in aggregates
        )
        self.repository.append_event(
            orchestration_id,
            "PROVISIONAL_EVIDENCE_AGGREGATED",
            {
                "aggregate_run_id": preview["aggregate_run_id"],
                "aggregate_version_ids": record["downstream"]["aggregate_version_ids"],
                "uncertainty": [
                    item.get("uncertainty_dimensions", {}) for item in aggregates
                ],
                "contradictions": sum(
                    item.get("contradictory_evidence_count", 0) for item in aggregates
                ),
            },
        )

        risk_class = self._risk_class(candidates, aggregates)
        routing = self._route(risk_class, publication_requested=publication_requested)
        record["risk_class"] = risk_class.value
        record["routing_outcome"] = routing.value
        if routing is RoutingOutcome.PROVISIONAL_KNOWLEDGE:
            record["state"] = "PROVISIONAL_SCIENTIFIC_RECORD"
            record["lifecycle_state"] = "PROVISIONAL_SCIENTIFIC_RECORD"
        elif routing is RoutingOutcome.PUBLICATION_REVIEW_REQUIRED:
            record["state"] = "PUBLICATION_REVIEW_REQUIRED"
            record["lifecycle_state"] = "PROVISIONAL_SCIENTIFIC_RECORD"
            record["publication_status"] = "REVIEW_REQUIRED"
        else:
            record["state"] = "REVIEW_ROUTED"
            record["lifecycle_state"] = "PROVISIONAL_SCIENTIFIC_RECORD"
            record["blockers"] = [routing.value]

        self.repository.append_event(
            orchestration_id,
            "RISK_CLASSIFIED_AND_ROUTED",
            {
                "risk_class": risk_class.value,
                "routing_outcome": routing.value,
                "publication_requested": publication_requested,
            },
        )
        self.repository.save(record)
        record["history"] = self.repository.history(orchestration_id)
        return record

    def status(self, orchestration_id: str) -> dict[str, Any]:
        record = self.repository.get(orchestration_id)
        if not record:
            raise ScientificOrchestrationError("ORCHESTRATION_NOT_FOUND")
        record["history"] = self.repository.history(orchestration_id)
        return record
