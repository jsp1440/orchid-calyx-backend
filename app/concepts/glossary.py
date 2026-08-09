from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from .lexical import normalize_lexical_value
from .services import ConceptRegistryService


class CandidateState(StrEnum):
    UNRESOLVED = "UNRESOLVED"
    CANDIDATES = "CANDIDATES"
    AMBIGUOUS = "AMBIGUOUS"
    MATCHED_PENDING_REVIEW = "MATCHED_PENDING_REVIEW"
    REVIEWED_MATCH = "REVIEWED_MATCH"
    NEW_CONCEPT_CANDIDATE = "NEW_CONCEPT_CANDIDATE"
    REJECTED = "REJECTED"


class FigureRequestType(StrEnum):
    DIAGRAM = "DIAGRAM"
    SKETCH = "SKETCH"
    COLOR_ILLUSTRATION = "COLOR_ILLUSTRATION"
    PHOTO_SET = "PHOTO_SET"
    ANIMATION = "ANIMATION"
    COMPARISON_PLATE = "COMPARISON_PLATE"
    DISSECTION = "DISSECTION"


@dataclass(frozen=True, slots=True)
class GlossaryCandidateInput:
    term: str
    source_uri: str
    source_revision_id: str
    source_checksum: str
    evidence_span_id: str
    language: str = "en"


class GlossaryRepository(Protocol):
    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None: ...
    def insert_candidate(self, row: Mapping[str, Any]) -> dict[str, Any]: ...
    def list_candidates(self, *, state: str | None, limit: int) -> list[dict[str, Any]]: ...
    def review_candidate(self, candidate_id: str, updates: Mapping[str, Any]) -> dict[str, Any] | None: ...
    def get_figure_request(self, request_id: str) -> dict[str, Any] | None: ...
    def insert_figure_request(self, row: Mapping[str, Any]) -> dict[str, Any]: ...
    def list_figure_requests(self, *, concept_id: UUID | None, limit: int) -> list[dict[str, Any]]: ...


def _sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _candidate_id(value: GlossaryCandidateInput) -> str:
    return _sha256(
        {
            "schema": "calyx-glossary-candidate/v1",
            "term": normalize_lexical_value(value.term),
            "source_uri": value.source_uri,
            "source_revision_id": value.source_revision_id,
            "source_checksum": value.source_checksum.lower(),
            "evidence_span_id": value.evidence_span_id,
            "language": value.language,
        }
    )


class GlossaryService:
    def __init__(self, repository: GlossaryRepository, concepts: ConceptRegistryService) -> None:
        self.repository = repository
        self.concepts = concepts

    def intake(self, value: GlossaryCandidateInput) -> dict[str, Any]:
        normalized = normalize_lexical_value(value.term)
        if not normalized:
            raise ValueError("GLOSSARY_TERM_REQUIRED")
        if not value.source_uri.strip() or not value.source_revision_id.strip() or not value.evidence_span_id.strip():
            raise ValueError("GLOSSARY_SOURCE_PROVENANCE_REQUIRED")
        checksum = value.source_checksum.strip().lower()
        if len(checksum) != 64 or any(ch not in "0123456789abcdef" for ch in checksum):
            raise ValueError("GLOSSARY_SOURCE_CHECKSUM_INVALID")

        candidate_id = _candidate_id(value)
        existing = self.repository.get_candidate(candidate_id)
        if existing is not None:
            return existing

        resolution = self.concepts.search_concepts(value.term, language=value.language, limit=25)
        concept_ids = tuple(resolution.get("exact_concept_ids") or ())
        state = {
            "RESOLVED": CandidateState.MATCHED_PENDING_REVIEW,
            "AMBIGUOUS": CandidateState.AMBIGUOUS,
            "CANDIDATES": CandidateState.CANDIDATES,
            "UNRESOLVED": CandidateState.UNRESOLVED,
        }[resolution["resolution"]]
        row = {
            "candidate_id": candidate_id,
            "term": value.term.strip(),
            "normalized_term": normalized,
            "language": value.language.strip() or "und",
            "source_uri": value.source_uri.strip(),
            "source_revision_id": value.source_revision_id.strip(),
            "source_checksum": checksum,
            "evidence_span_id": value.evidence_span_id.strip(),
            "resolution_state": state.value,
            "matched_concept_ids": list(concept_ids),
            "reviewed_concept_id": None,
            "reviewed_by": None,
            "review_rationale": None,
            "automatic_concept_promotion": False,
            "knowledge_graph_publication_authorized": False,
        }
        return self.repository.insert_candidate(row)

    def list_candidates(self, *, state: CandidateState | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return self.repository.list_candidates(state=state.value if state else None, limit=max(1, min(limit, 200)))

    def review_candidate(
        self,
        candidate_id: str,
        *,
        state: CandidateState,
        actor: str,
        rationale: str,
        concept_id: UUID | None = None,
    ) -> dict[str, Any]:
        existing = self.repository.get_candidate(candidate_id)
        if existing is None:
            raise LookupError("GLOSSARY_CANDIDATE_NOT_FOUND")
        if state not in {CandidateState.REVIEWED_MATCH, CandidateState.NEW_CONCEPT_CANDIDATE, CandidateState.REJECTED}:
            raise ValueError("GLOSSARY_REVIEW_STATE_INVALID")
        if not actor.strip() or not rationale.strip():
            raise ValueError("GLOSSARY_REVIEW_EVIDENCE_REQUIRED")
        if state is CandidateState.REVIEWED_MATCH:
            if concept_id is None:
                raise ValueError("GLOSSARY_REVIEWED_MATCH_CONCEPT_REQUIRED")
            self.concepts.get_concept(concept_id)
        elif concept_id is not None:
            raise ValueError("GLOSSARY_CONCEPT_ONLY_ALLOWED_FOR_REVIEWED_MATCH")
        result = self.repository.review_candidate(
            candidate_id,
            {
                "resolution_state": state.value,
                "reviewed_concept_id": concept_id,
                "reviewed_by": actor.strip(),
                "review_rationale": rationale.strip(),
            },
        )
        if result is None:
            raise LookupError("GLOSSARY_CANDIDATE_NOT_FOUND")
        return result

    def glossary_entry(self, concept_id: UUID) -> dict[str, Any]:
        concept = self.concepts.get_concept(concept_id)
        labels = self.concepts.list_labels(concept_id)
        definitions = self.concepts.list_definitions(concept_id)
        return {
            "schema": "calyx-canonical-glossary-entry/v1",
            "concept_id": concept["concept_id"],
            "concept_uri": concept["concept_uri"],
            "status": concept["status"],
            "review_state": concept["review_state"],
            "labels": labels,
            "definitions": definitions,
            "canonical_source": "app.concepts",
            "generated_definition": False,
        }

    def create_figure_request(
        self,
        *,
        concept_id: UUID,
        request_type: FigureRequestType,
        audience: str,
        purpose: str,
        source_candidate_id: str | None = None,
    ) -> dict[str, Any]:
        self.concepts.get_concept(concept_id)
        if source_candidate_id is not None and self.repository.get_candidate(source_candidate_id) is None:
            raise LookupError("GLOSSARY_CANDIDATE_NOT_FOUND")
        payload = {
            "schema": "calyx-glossary-figure-request/v1",
            "concept_id": str(concept_id),
            "request_type": request_type.value,
            "audience": audience.strip(),
            "purpose": purpose.strip(),
            "source_candidate_id": source_candidate_id,
        }
        if not payload["audience"] or not payload["purpose"]:
            raise ValueError("GLOSSARY_FIGURE_REQUEST_TEXT_REQUIRED")
        request_id = _sha256(payload)
        existing = self.repository.get_figure_request(request_id)
        if existing is not None:
            return existing
        return self.repository.insert_figure_request(
            {
                "request_id": request_id,
                **payload,
                "review_state": "PENDING",
                "figure_is_scientific_evidence": False,
                "automatic_generation_authorized": False,
                "automatic_publication_authorized": False,
            }
        )

    def list_figure_requests(self, *, concept_id: UUID | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return self.repository.list_figure_requests(concept_id=concept_id, limit=max(1, min(limit, 200)))
