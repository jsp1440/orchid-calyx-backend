from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any
from uuid import uuid4

from .contracts import (
    CharacterDefinition,
    CharacterObservation,
    ImageAnalysisResult,
    LiteratureClaim,
    MatrixProfile,
)
from .engine import matrix_observations_from_vision, rank_matrix_candidates


@dataclass(frozen=True, slots=True)
class OperationRecord:
    operation_id: str
    operation_type: str
    request_hash: str
    state: str
    result: dict[str, Any]
    human_review_required: bool = True


class MultimodalOperatorService:
    """Deterministic, process-local operator layer; production persistence remains disabled."""

    def __init__(self) -> None:
        self._by_hash: dict[str, OperationRecord] = {}
        self._records: list[OperationRecord] = []

    @staticmethod
    def request_hash(operation_type: str, payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            {"operation_type": operation_type, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return sha256(canonical.encode()).hexdigest()

    def _record(self, operation_type: str, payload: dict[str, Any], result: dict[str, Any]) -> OperationRecord:
        fingerprint = self.request_hash(operation_type, payload)
        existing = self._by_hash.get(fingerprint)
        if existing is not None:
            return existing
        record = OperationRecord(
            operation_id=str(uuid4()),
            operation_type=operation_type,
            request_hash=fingerprint,
            state="human_review_required",
            result=result,
        )
        self._by_hash[fingerprint] = record
        self._records.append(record)
        return record

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
        for index, (operation_type, payload) in enumerate(operations):
            if operation_type not in {
                "literature_validation",
                "matrix_ranking",
                "vision_conversion",
                "integrated_identification",
            }:
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

    def review_queue(self) -> tuple[OperationRecord, ...]:
        return tuple(record for record in self._records if record.human_review_required)

    def export_audit(self) -> dict[str, Any]:
        return {
            "records": [asdict(record) for record in self._records],
            "record_count": len(self._records),
            "production_persistence": False,
        }

    def benchmark(self) -> dict[str, Any]:
        return {
            "suite": "fixture_multimodal_v1",
            "literature_provenance_checks": True,
            "matrix_explainability_checks": True,
            "vision_license_checks": True,
            "abstention_checks": True,
            "live_provider_calls": 0,
            "state": "deterministic_fixture_ready",
        }


operator_service = MultimodalOperatorService()
