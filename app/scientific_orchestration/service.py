from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from app.evidence_aggregation.models import CandidateInput


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


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

    def append_event(self, orchestration_id: str, event_type: str, details: dict[str, Any]) -> None:
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
        return [deepcopy(item) for item in self.events if item["orchestration_id"] == orchestration_id]


class GovernedScientificOrchestrationService:
    """Review-preserving orchestration across existing scientific components."""

    def __init__(
        self,
        *,
        candidate_repository: Any,
        aggregation_service: Any,
        aggregation_repository: Any,
        interpretation_service: Any,
        interpretation_repository: Any,
        repository: MemoryScientificOrchestrationRepository | None = None,
    ) -> None:
        self.candidates = candidate_repository
        self.aggregation = aggregation_service
        self.aggregates = aggregation_repository
        self.interpretation = interpretation_service
        self.interpretations = interpretation_repository
        self.repository = repository or MemoryScientificOrchestrationRepository()

    def _reviewed_candidates(self, candidate_run_id: int) -> list[dict[str, Any]]:
        candidates = self.candidates.candidates_for_run(candidate_run_id)
        if not candidates:
            raise ScientificOrchestrationError("CANDIDATE_RUN_EMPTY")
        rejected = [c["candidate_id"] for c in candidates if c["review_state"] == "REJECTED"]
        pending = [c["candidate_id"] for c in candidates if c["review_state"] != "APPROVED"]
        if rejected:
            raise ScientificOrchestrationError("CANDIDATE_REVIEW_REJECTED", {"candidate_ids": rejected})
        if pending:
            raise ScientificOrchestrationError("CANDIDATE_REVIEW_REQUIRED", {"candidate_ids": pending})
        if any(c.get("published") for c in candidates):
            raise ScientificOrchestrationError("CANDIDATE_ALREADY_PUBLISHED")
        return candidates

    def _candidate_input(self, candidate: dict[str, Any]) -> CandidateInput:
        links = [
            item for item in self.candidates.evidence_links
            if item["candidate_id"] == candidate["candidate_id"]
        ]
        if not links:
            raise ScientificOrchestrationError(
                "INCOMPLETE_EVIDENCE", {"candidate_id": candidate["candidate_id"]}
            )
        revision_ids = {item["revision_id"] for item in links}
        if len(revision_ids) != 1:
            raise ScientificOrchestrationError(
                "STALE_OR_CONFLICTING_REVISION", {"candidate_id": candidate["candidate_id"]}
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
            source_anchor_ids=tuple(sorted(item["anchor"]["anchor_id"] for item in links)),
            evidence_type=str(candidate.get("method") or "LITERATURE"),
            source_class="PRIMARY",
            directness="DIRECT_OBSERVATION",
            document_hash=links[0]["anchor"].get("locator", {}).get("source_hash"),
            confidence=float(candidate.get("confidence", 0.5)),
            review_state="APPROVED",
            display_policy=str(links[0].get("display_policy") or "UNKNOWN_REQUIRES_REVIEW"),
            metadata={"candidate": deepcopy(candidate), "evidence_links": deepcopy(links)},
        )

    def continue_run(self, candidate_run_id: int) -> dict[str, Any]:
        candidates = self._reviewed_candidates(candidate_run_id)
        signature = {
            "candidate_run_id": candidate_run_id,
            "candidate_versions": sorted(
                f"{item['candidate_id']}:{item['version']}" for item in candidates
            ),
        }
        orchestration_id = _fingerprint(signature)
        existing = self.repository.get(orchestration_id)
        if existing and existing["state"] in {"PUBLICATION_ELIGIBLE", "PUBLICATION_BLOCKED"}:
            existing["reused"] = True
            existing["history"] = self.repository.history(orchestration_id)
            return existing

        record = existing or {
            "orchestration_id": orchestration_id,
            "candidate_run_id": candidate_run_id,
            "candidate_ids": sorted(item["candidate_id"] for item in candidates),
            "state": "REVIEW_VERIFIED",
            "published": False,
            "publication_status": "NOT_EVALUATED",
            "blockers": [],
            "downstream": {},
            "created_at": _now(),
        }
        if not existing:
            self.repository.append_event(orchestration_id, "CANDIDATE_REVIEW_VERIFIED", signature)

        candidate_inputs = [self._candidate_input(item) for item in candidates]
        preview = self.aggregation.preview(candidate_inputs)
        aggregation_result = self.aggregation.execute(preview["aggregate_run_id"])
        aggregates = [
            item for item in self.aggregates.aggregates
            if item.get("aggregate_version_id")
            and set(item.get("contributing_candidate_ids", ())).issubset(set(record["candidate_ids"]))
        ]
        if not aggregates:
            raise ScientificOrchestrationError("AGGREGATION_RESULT_MISSING")
        if any(item.get("conflicting_evidence_count", 0) > 0 for item in aggregates):
            record["state"] = "PUBLICATION_BLOCKED"
            record["publication_status"] = "BLOCKED"
            record["blockers"] = ["UNRESOLVED_CONTRADICTION"]
            record["downstream"]["aggregate_run_id"] = preview["aggregate_run_id"]
            self.repository.append_event(
                orchestration_id,
                "AGGREGATION_BLOCKED_BY_CONTRADICTION",
                {"aggregate_run_id": preview["aggregate_run_id"]},
            )
            self.repository.save(record)
            record["history"] = self.repository.history(orchestration_id)
            return record

        aggregate = sorted(aggregates, key=lambda x: x["aggregate_version_id"])[-1]
        record["downstream"]["aggregate_run_id"] = preview["aggregate_run_id"]
        record["downstream"]["aggregate_version_id"] = aggregate["aggregate_version_id"]
        record["state"] = "AGGREGATED"
        self.repository.append_event(
            orchestration_id,
            "EVIDENCE_AGGREGATED",
            {
                "aggregate_run_id": preview["aggregate_run_id"],
                "aggregate_version_id": aggregate["aggregate_version_id"],
                "uncertainty": aggregate.get("uncertainty_dimensions", {}),
                "contradictions": aggregate.get("contradictory_evidence_count", 0),
            },
        )

        packet = self.interpretation.construct_packet(
            packet_key=f"orchestration:{orchestration_id}",
            context_form=__import__(
                "app.scientific_interpretation.models", fromlist=["ContextForm"]
            ).ContextForm.SEMANTIC_CONTEXT,
            sources=tuple(),
            context_dimensions={},
            material_dimensions=tuple(),
            structural_relationships=tuple(),
            construction_policy_version="calyx-brain-001c",
            boundary_analyzer_version="calyx-brain-001c",
            construction_rationale="Governed aggregate-to-interpretation transition",
        )
        raise ScientificOrchestrationError(
            "INTERPRETATION_PACKET_REQUIRES_SOURCE_REFERENCES",
            {"aggregate_version_id": aggregate["aggregate_version_id"], "packet": asdict(packet) if hasattr(packet, "__dataclass_fields__") else packet},
        )

    def status(self, orchestration_id: str) -> dict[str, Any]:
        record = self.repository.get(orchestration_id)
        if not record:
            raise ScientificOrchestrationError("ORCHESTRATION_NOT_FOUND")
        record["history"] = self.repository.history(orchestration_id)
        return record
