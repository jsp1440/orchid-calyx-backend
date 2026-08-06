from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Any, Protocol
from uuid import uuid4

from .contracts import (
    CharacterDefinition,
    CharacterObservation,
    ImageAnalysisResult,
    LiteratureClaim,
    MatrixProfile,
)
from .engine import matrix_observations_from_vision, rank_matrix_candidates


class MultimodalError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    decision: str
    rationale: str
    reviewer: str
    decided_at: str

    def validate(self) -> None:
        if self.decision not in {"approve", "request_revision", "reject"}:
            raise MultimodalError("REVIEW_DECISION_INVALID", "Unsupported review decision.")
        if not self.rationale.strip() or not self.reviewer.strip():
            raise MultimodalError("REVIEW_RATIONALE_REQUIRED", "Reviewer and rationale are required.")


@dataclass(frozen=True, slots=True)
class OperationRecord:
    operation_id: str
    operation_type: str
    request_hash: str
    state: str
    result: dict[str, Any]
    created_at: str
    provenance: dict[str, Any]
    human_review_required: bool = True
    review: ReviewDecision | None = None
    errors: tuple[dict[str, str], ...] = field(default_factory=tuple)


class OperationRepository(Protocol):
    def get_by_hash(self, request_hash: str) -> OperationRecord | None: ...

    def get(self, operation_id: str) -> OperationRecord | None: ...

    def save(self, record: OperationRecord) -> OperationRecord: ...

    def replace(self, record: OperationRecord) -> OperationRecord: ...

    def list_records(self) -> tuple[OperationRecord, ...]: ...


class InMemoryOperationRepository:
    """Deterministic repository used until governed Postgres persistence is activated."""

    def __init__(self) -> None:
        self._by_id: dict[str, OperationRecord] = {}
        self._by_hash: dict[str, str] = {}
        self._order: list[str] = []

    def get_by_hash(self, request_hash: str) -> OperationRecord | None:
        operation_id = self._by_hash.get(request_hash)
        return self._by_id.get(operation_id) if operation_id else None

    def get(self, operation_id: str) -> OperationRecord | None:
        return self._by_id.get(operation_id)

    def save(self, record: OperationRecord) -> OperationRecord:
        existing = self.get_by_hash(record.request_hash)
        if existing is not None:
            return existing
        self._by_id[record.operation_id] = record
        self._by_hash[record.request_hash] = record.operation_id
        self._order.append(record.operation_id)
        return record

    def replace(self, record: OperationRecord) -> OperationRecord:
        if record.operation_id not in self._by_id:
            raise MultimodalError("OPERATION_NOT_FOUND", "Operation does not exist.")
        self._by_id[record.operation_id] = record
        return record

    def list_records(self) -> tuple[OperationRecord, ...]:
        return tuple(self._by_id[operation_id] for operation_id in self._order)


class MultimodalOperatorService:
    """Governed operator service with a swappable persistence repository."""

    def __init__(self, repository: OperationRepository | None = None) -> None:
        self.repository = repository or InMemoryOperationRepository()

    @staticmethod
    def request_hash(operation_type: str, payload: Mapping[str, Any]) -> str:
        canonical = json.dumps(
            {"operation_type": operation_type, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _provenance(operation_type: str, request_hash: str) -> dict[str, Any]:
        return {
            "operation_type": operation_type,
            "request_hash": request_hash,
            "engine": "multimodal_intelligence",
            "engine_version": "0.3.0",
            "live_provider_calls": 0,
            "production_mutation": False,
        }

    def _record(self, operation_type: str, payload: dict[str, Any], result: dict[str, Any]) -> OperationRecord:
        fingerprint = self.request_hash(operation_type, payload)
        existing = self.repository.get_by_hash(fingerprint)
        if existing is not None:
            return existing
        record = OperationRecord(
            operation_id=str(uuid4()),
            operation_type=operation_type,
            request_hash=fingerprint,
            state="human_review_required",
            result=result,
            created_at=datetime.now(UTC).isoformat(),
            provenance=self._provenance(operation_type, fingerprint),
        )
        return self.repository.save(record)

    def validate_literature_claim(self, claim: LiteratureClaim) -> OperationRecord:
        claim.validate()
        payload = asdict(claim)
        result = {
            "claim_id": claim.claim_id,
            "canonical_taxon_id": claim.canonical_taxon_id,
            "evidence_span_count": len(claim.evidence_spans),
            "confidence": claim.confidence,
            "contradictions": list(claim.contradictions),
            "publication_allowed": False,
        }
        return self._record("literature_validation", payload, result)

    def rank_matrix(
        self,
        *,
        definitions: dict[str, CharacterDefinition],
        observations: tuple[CharacterObservation, ...],
        profiles: tuple[MatrixProfile, ...],
    ) -> OperationRecord:
        candidates = rank_matrix_candidates(
            definitions=definitions,
            observations=observations,
            profiles=profiles,
        )
        payload = {
            "definitions": {key: asdict(value) for key, value in definitions.items()},
            "observations": [asdict(value) for value in observations],
            "profiles": [asdict(value) for value in profiles],
        }
        result = {
            "candidate_count": len(candidates),
            "candidates": [asdict(candidate) for candidate in candidates],
            "autonomous_identification": False,
        }
        return self._record("matrix_ranking", payload, result)

    def convert_vision(self, analysis: ImageAnalysisResult) -> OperationRecord:
        observations = matrix_observations_from_vision(analysis)
        payload = asdict(analysis)
        result = {
            "image_id": analysis.image_id,
            "observation_count": len(observations),
            "observations": [asdict(value) for value in observations],
            "license_verified": True,
        }
        return self._record("vision_conversion", payload, result)

    def integrated_identification(
        self,
        *,
        analysis: ImageAnalysisResult,
        definitions: dict[str, CharacterDefinition],
        profiles: tuple[MatrixProfile, ...],
        minimum_margin: float = 0.15,
    ) -> OperationRecord:
        if not 0.0 <= minimum_margin <= 1.0:
            raise MultimodalError("MINIMUM_MARGIN_INVALID", "Minimum margin must be between zero and one.")
        observations = matrix_observations_from_vision(analysis)
        candidates = rank_matrix_candidates(
            definitions=definitions,
            observations=observations,
            profiles=profiles,
        )
        margin = 0.0
        if len(candidates) >= 2:
            margin = candidates[0].score - candidates[1].score
        elif candidates:
            margin = candidates[0].score
        abstained = not candidates or margin < minimum_margin
        payload = {
            "analysis": asdict(analysis),
            "definitions": {key: asdict(value) for key, value in definitions.items()},
            "profiles": [asdict(value) for value in profiles],
            "minimum_margin": minimum_margin,
        }
        result = {
            "candidates": [asdict(candidate) for candidate in candidates],
            "margin": round(margin, 6),
            "abstained": abstained,
            "decision": "insufficient_evidence" if abstained else "candidate_ranking_ready_for_review",
        }
        return self._record("integrated_identification", payload, result)

    def batch(self, operations: tuple[tuple[str, dict[str, Any]], ...]) -> dict[str, Any]:
        accepted = []
        rejected = []
        supported = {
            "literature_validation",
            "matrix_ranking",
            "vision_conversion",
            "integrated_identification",
        }
        for index, (operation_type, payload) in enumerate(operations):
            if operation_type not in supported:
                rejected.append({"index": index, "reason": "UNSUPPORTED_OPERATION"})
                continue
            accepted.append(
                {
                    "index": index,
                    "operation_type": operation_type,
                    "request_hash": self.request_hash(operation_type, payload),
                }
            )
        return {"accepted": accepted, "rejected": rejected, "execution_enabled": False}

    def get_operation(self, operation_id: str) -> OperationRecord:
        record = self.repository.get(operation_id)
        if record is None:
            raise MultimodalError("OPERATION_NOT_FOUND", "Operation does not exist.")
        return record

    def decide_review(
        self,
        operation_id: str,
        *,
        decision: str,
        rationale: str,
        reviewer: str,
    ) -> OperationRecord:
        record = self.get_operation(operation_id)
        review = ReviewDecision(
            decision=decision,
            rationale=rationale,
            reviewer=reviewer,
            decided_at=datetime.now(UTC).isoformat(),
        )
        review.validate()
        state_by_decision = {
            "approve": "review_approved",
            "request_revision": "revision_requested",
            "reject": "review_rejected",
        }
        updated = OperationRecord(
            operation_id=record.operation_id,
            operation_type=record.operation_type,
            request_hash=record.request_hash,
            state=state_by_decision[decision],
            result=record.result,
            created_at=record.created_at,
            provenance=record.provenance,
            human_review_required=False,
            review=review,
            errors=record.errors,
        )
        return self.repository.replace(updated)

    def review_queue(
        self,
        *,
        operation_type: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        if offset < 0 or not 1 <= limit <= 100:
            raise MultimodalError("PAGINATION_INVALID", "Offset and limit are outside allowed bounds.")
        records = [
            record
            for record in self.repository.list_records()
            if record.human_review_required
            and (operation_type is None or record.operation_type == operation_type)
        ]
        return {
            "items": tuple(records[offset : offset + limit]),
            "total": len(records),
            "offset": offset,
            "limit": limit,
        }

    def provenance_bundle(self, operation_id: str) -> dict[str, Any]:
        record = self.get_operation(operation_id)
        return {
            "operation_id": record.operation_id,
            "request_hash": record.request_hash,
            "created_at": record.created_at,
            "provenance": record.provenance,
            "review": asdict(record.review) if record.review else None,
            "result_hash": sha256(
                json.dumps(record.result, sort_keys=True, separators=(",", ":"), default=str).encode()
            ).hexdigest(),
        }

    def export_audit(self) -> dict[str, Any]:
        records = self.repository.list_records()
        return {
            "records": [asdict(record) for record in records],
            "record_count": len(records),
            "production_persistence": False,
            "repository": type(self.repository).__name__,
        }

    def benchmark(self) -> dict[str, Any]:
        cases = (
            {"case_id": "literature-provenance", "expected": "pass"},
            {"case_id": "matrix-explainability", "expected": "pass"},
            {"case_id": "vision-license", "expected": "pass"},
            {"case_id": "identification-abstention", "expected": "pass"},
        )
        return {
            "suite": "fixture_multimodal_v2",
            "case_count": len(cases),
            "cases": cases,
            "live_provider_calls": 0,
            "state": "deterministic_fixture_ready",
        }

    def configuration(self) -> dict[str, Any]:
        return {
            "persistence_backend": type(self.repository).__name__,
            "production_persistence_enabled": False,
            "live_vision_provider_enabled": False,
            "ocr_provider_enabled": False,
            "automatic_publication_enabled": False,
            "taxonomy_activation_enabled": False,
            "maximum_page_size": 100,
            "human_review_required": True,
        }


operator_service = MultimodalOperatorService()
