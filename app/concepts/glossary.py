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
    def list_figure_requests(
        self,
        *,
        concept_id: UUID | None,
        source_candidate_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]: ...


def _sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _candidate_id(value: GlossaryCandidateInput) -> str:
    return _sha256(
        {
            "schema": "calyx-glossary-candidate/v1",
            "term": normalize_lexical_value(value.term),
            "source_uri": value.source_uri.strip(),
            "source_revision_id": value.source_revision_id.strip(),
            "source_checksum": value.source_checksum.strip().lower(),
            "evidence_span_id": value.evidence_span_id.strip(),
            "language": value.language.strip() or "und",
        }
    )


def _possible_concept_ids(resolution: Mapping[str, Any]) -> list[str]:
    concept_ids = {str(value) for value in resolution.get("exact_concept_ids", []) if value is not None}
    for match in resolution.get("matches", []):
        if isinstance(match, Mapping) and match.get("concept_id") is not None:
            concept_ids.add(str(match["concept_id"]))
    return sorted(concept_ids)


def _preferred_label(labels: list[dict[str, Any]], fallback: str) -> str:
    for row in labels:
        if str(row.get("label_type") or "").upper() == "PREFERRED" and str(row.get("label") or "").strip():
            return str(row["label"]).strip()
    for row in labels:
        if str(row.get("label") or "").strip():
            return str(row["label"]).strip()
    return fallback


def _definition_text(definitions: list[dict[str, Any]]) -> str | None:
    for definition_type in ("SCIENTIFIC", "GLOSSARY", "LEARNER", "PLAIN_LANGUAGE"):
        for row in definitions:
            if str(row.get("definition_type") or "").upper() == definition_type and str(row.get("text") or "").strip():
                return str(row["text"]).strip()
    for row in definitions:
        if str(row.get("text") or "").strip():
            return str(row["text"]).strip()
    return None


def _figure_brief(
    *,
    subject_label: str,
    request_type: FigureRequestType,
    audience: str,
    purpose: str,
    definition: str | None,
    candidate_requires_review: bool,
) -> dict[str, str]:
    readable_type = request_type.value.replace("_", " ").title()
    title = f"{subject_label} — {readable_type}"
    if candidate_requires_review:
        status = "CANDIDATE_REQUIRES_REVIEW"
        context = (
            "This subject is a glossary candidate and has not been approved as a canonical scientific concept. "
            "Use only supplied source context; do not invent morphology, relationships, measurements, taxa, labels, or claims."
        )
        caption = (
            f"{subject_label}. Draft {readable_type.lower()} request for a glossary candidate; "
            "scientific content requires review before publication."
        )
    else:
        status = "CANONICAL_CONCEPT"
        context = (
            f"Canonical glossary definition reference: {definition}"
            if definition
            else "The subject is a reviewed canonical concept, but no definition is available in this projection. Do not infer missing scientific details."
        )
        caption = (
            f"{subject_label}. Draft educational {readable_type.lower()} for the canonical Orchid Continuum glossary; "
            "verify labels and scientific details before publication."
        )
    prompt = (
        f'Create a scientifically conservative {readable_type.lower()} for the Orchid Continuum glossary subject "{subject_label}" '
        f'for audience "{audience}". Purpose: {purpose}. Scientific context: {context} '
        "Requirements: botanical and scientific accuracy; readable labels; uncluttered composition; reserve clear title and caption areas; "
        "do not fabricate structures, traits, measurements, ecological relationships, taxa, or scale. "
        "If the supplied evidence is insufficient, return NEEDS_SCIENTIFIC_REVIEW rather than guessing."
    )
    return {
        "scientific_context_status": status,
        "suggested_title": title,
        "suggested_caption": caption,
        "provider_prompt": prompt,
    }


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
        if len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum):
            raise ValueError("GLOSSARY_SOURCE_CHECKSUM_INVALID")
        candidate_id = _candidate_id(value)
        existing = self.repository.get_candidate(candidate_id)
        if existing is not None:
            return existing
        resolution = self.concepts.search_concepts(value.term, language=value.language, limit=25)
        state = {
            "RESOLVED": CandidateState.MATCHED_PENDING_REVIEW,
            "AMBIGUOUS": CandidateState.AMBIGUOUS,
            "CANDIDATES": CandidateState.CANDIDATES,
            "UNRESOLVED": CandidateState.UNRESOLVED,
        }[resolution["resolution"]]
        return self.repository.insert_candidate(
            {
                "candidate_id": candidate_id,
                "term": value.term.strip(),
                "normalized_term": normalized,
                "language": value.language.strip() or "und",
                "source_uri": value.source_uri.strip(),
                "source_revision_id": value.source_revision_id.strip(),
                "source_checksum": checksum,
                "evidence_span_id": value.evidence_span_id.strip(),
                "resolution_state": state.value,
                "matched_concept_ids": _possible_concept_ids(resolution),
                "reviewed_concept_id": None,
                "reviewed_by": None,
                "review_rationale": None,
                "automatic_concept_promotion": False,
                "knowledge_graph_publication_authorized": False,
            }
        )

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
        final_states = {CandidateState.REVIEWED_MATCH, CandidateState.NEW_CONCEPT_CANDIDATE, CandidateState.REJECTED}
        if state not in final_states:
            raise ValueError("GLOSSARY_REVIEW_STATE_INVALID")
        normalized_actor = actor.strip()
        normalized_rationale = rationale.strip()
        if not normalized_actor or not normalized_rationale:
            raise ValueError("GLOSSARY_REVIEW_EVIDENCE_REQUIRED")
        if state is CandidateState.REVIEWED_MATCH:
            if concept_id is None:
                raise ValueError("GLOSSARY_REVIEWED_MATCH_CONCEPT_REQUIRED")
            self.concepts.get_concept(concept_id)
        elif concept_id is not None:
            raise ValueError("GLOSSARY_CONCEPT_ONLY_ALLOWED_FOR_REVIEWED_MATCH")
        current_state = CandidateState(existing["resolution_state"])
        if current_state in final_states:
            same_decision = (
                current_state is state
                and str(existing.get("reviewed_concept_id") or "") == str(concept_id or "")
                and existing.get("reviewed_by") == normalized_actor
                and existing.get("review_rationale") == normalized_rationale
            )
            if same_decision:
                return existing
            raise ValueError("GLOSSARY_REVIEW_DECISION_IMMUTABLE")
        result = self.repository.review_candidate(
            candidate_id,
            {
                "resolution_state": state.value,
                "reviewed_concept_id": concept_id,
                "reviewed_by": normalized_actor,
                "review_rationale": normalized_rationale,
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
        concept_id: UUID | None,
        request_type: FigureRequestType,
        audience: str,
        purpose: str,
        source_candidate_id: str | None = None,
    ) -> dict[str, Any]:
        if concept_id is None and source_candidate_id is None:
            raise ValueError("GLOSSARY_FIGURE_SUBJECT_REQUIRED")
        normalized_audience = audience.strip()
        normalized_purpose = purpose.strip()
        if not normalized_audience or not normalized_purpose:
            raise ValueError("GLOSSARY_FIGURE_REQUEST_TEXT_REQUIRED")

        candidate = None
        if source_candidate_id is not None:
            candidate = self.repository.get_candidate(source_candidate_id)
            if candidate is None:
                raise LookupError("GLOSSARY_CANDIDATE_NOT_FOUND")
            if CandidateState(candidate["resolution_state"]) is CandidateState.REJECTED:
                raise ValueError("GLOSSARY_REJECTED_CANDIDATE_FIGURE_FORBIDDEN")

        concept = None
        labels: list[dict[str, Any]] = []
        definitions: list[dict[str, Any]] = []
        if concept_id is not None:
            concept = self.concepts.get_concept(concept_id)
            labels = self.concepts.list_labels(concept_id)
            definitions = self.concepts.list_definitions(concept_id)

        if concept_id is not None and candidate is not None:
            if (
                CandidateState(candidate["resolution_state"]) is not CandidateState.REVIEWED_MATCH
                or str(candidate.get("reviewed_concept_id") or "") != str(concept_id)
            ):
                raise ValueError("GLOSSARY_FIGURE_PROVENANCE_MISMATCH")

        candidate_requires_review = concept_id is None
        if candidate_requires_review:
            subject_label = str(candidate["term"]).strip()
            definition = None
        else:
            fallback = str(candidate["term"]).strip() if candidate is not None else str(concept["concept_uri"])
            subject_label = _preferred_label(labels, fallback)
            definition = _definition_text(definitions)

        brief = _figure_brief(
            subject_label=subject_label,
            request_type=request_type,
            audience=normalized_audience,
            purpose=normalized_purpose,
            definition=definition,
            candidate_requires_review=candidate_requires_review,
        )
        payload = {
            "schema": "calyx-glossary-figure-request/v2",
            "concept_id": str(concept_id) if concept_id is not None else None,
            "request_type": request_type.value,
            "audience": normalized_audience,
            "purpose": normalized_purpose,
            "source_candidate_id": source_candidate_id,
            "subject_label": subject_label,
            **brief,
        }
        request_id = _sha256(payload)
        existing = self.repository.get_figure_request(request_id)
        if existing is not None:
            return existing
        return self.repository.insert_figure_request(
            {
                "request_id": request_id,
                **payload,
                "review_state": "PENDING",
                "review_required": True,
                "figure_is_scientific_evidence": False,
                "automatic_generation_authorized": False,
                "automatic_publication_authorized": False,
            }
        )

    def list_figure_requests(
        self,
        *,
        concept_id: UUID | None = None,
        source_candidate_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self.repository.list_figure_requests(
            concept_id=concept_id,
            source_candidate_id=source_candidate_id,
            limit=max(1, min(limit, 200)),
        )
