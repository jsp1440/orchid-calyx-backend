from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, NAMESPACE_URL, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .lexical import normalize_lexical_value
from .repositories import concept_database_url
from .services import ConceptRegistryService


class GlossaryResolutionState(StrEnum):
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


class GlossaryRepository(Protocol):
    def upsert_candidate(self, data: Mapping[str, Any]) -> dict[str, Any]: ...

    def list_candidates(
        self, *, resolution_state: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]: ...

    def upsert_figure_request(self, data: Mapping[str, Any]) -> dict[str, Any]: ...

    def list_figure_requests(
        self, *, concept_id: UUID | None = None, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]: ...


class PostgresGlossaryRepository:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or concept_database_url()

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def upsert_candidate(self, data: Mapping[str, Any]) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_concepts.glossary_candidates
                  (candidate_id, fingerprint, display_term, normalized_term, language,
                   source_kind, source_hash, source_locator, char_start, char_end,
                   resolution_state, matched_concept_id, proposed_definition,
                   provenance, review_state)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (fingerprint) DO UPDATE
                SET last_seen_at=NOW()
                RETURNING *
                """,
                (
                    data["candidate_id"],
                    data["fingerprint"],
                    data["display_term"],
                    data["normalized_term"],
                    data["language"],
                    data["source_kind"],
                    data["source_hash"],
                    Jsonb(dict(data["source_locator"])),
                    data.get("char_start"),
                    data.get("char_end"),
                    data["resolution_state"],
                    data.get("matched_concept_id"),
                    data.get("proposed_definition"),
                    Jsonb(dict(data.get("provenance") or {})),
                    data.get("review_state", "PENDING"),
                ),
            )
            return cur.fetchone()

    def list_candidates(
        self, *, resolution_state: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM oc_concepts.glossary_candidates
                WHERE (%s IS NULL OR resolution_state=%s)
                ORDER BY last_seen_at DESC, normalized_term, candidate_id
                LIMIT %s
                """,
                (resolution_state, resolution_state, limit),
            )
            return list(cur.fetchall())

    def upsert_figure_request(self, data: Mapping[str, Any]) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_concepts.glossary_figure_requests
                  (request_id, fingerprint, concept_id, request_type, title, caption,
                   generation_prompt, priority, provenance)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (fingerprint) DO UPDATE
                SET revised_at=NOW()
                RETURNING *
                """,
                (
                    data["request_id"],
                    data["fingerprint"],
                    data["concept_id"],
                    data["request_type"],
                    data["title"],
                    data.get("caption"),
                    data["generation_prompt"],
                    data["priority"],
                    Jsonb(dict(data.get("provenance") or {})),
                ),
            )
            return cur.fetchone()

    def list_figure_requests(
        self, *, concept_id: UUID | None = None, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM oc_concepts.glossary_figure_requests
                WHERE (%s IS NULL OR concept_id=%s)
                  AND (%s IS NULL OR status=%s)
                ORDER BY priority DESC, created_at, request_id
                LIMIT %s
                """,
                (concept_id, concept_id, status, status, limit),
            )
            return list(cur.fetchall())


def _stable_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(parts: list[str]) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


class ScientificLanguageService:
    def __init__(
        self,
        *,
        concept_service: ConceptRegistryService,
        repository: GlossaryRepository,
    ) -> None:
        self.concept_service = concept_service
        self.repository = repository

    def intake_candidate(
        self,
        *,
        term: str,
        source_kind: str,
        source_hash: str,
        source_locator: Mapping[str, Any],
        language: str = "und",
        char_start: int | None = None,
        char_end: int | None = None,
        proposed_definition: str | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        display_term = term.strip()
        normalized_term = normalize_lexical_value(display_term)
        if not normalized_term:
            raise ValueError("EMPTY_GLOSSARY_CANDIDATE")
        if not source_kind.strip() or not source_hash.strip():
            raise ValueError("GLOSSARY_SOURCE_REQUIRED")
        if (char_start is None) != (char_end is None):
            raise ValueError("GLOSSARY_SOURCE_SPAN_INCOMPLETE")
        if char_start is not None and (char_start < 0 or char_end < char_start):
            raise ValueError("GLOSSARY_SOURCE_SPAN_INVALID")

        resolution = self.concept_service.search_concepts(
            display_term, language=None if language == "und" else language, limit=10
        )
        matched_concept_id: UUID | None = None
        if resolution["resolution"] == "RESOLVED":
            state = GlossaryResolutionState.MATCHED_PENDING_REVIEW
            matched_concept_id = UUID(resolution["exact_concept_ids"][0])
        elif resolution["resolution"] == "AMBIGUOUS":
            state = GlossaryResolutionState.AMBIGUOUS
        elif resolution["resolution"] == "CANDIDATES":
            state = GlossaryResolutionState.CANDIDATES
        else:
            state = GlossaryResolutionState.UNRESOLVED

        fingerprint = _sha256(
            [
                normalized_term,
                language.strip() or "und",
                source_kind.strip(),
                source_hash.strip(),
                str(char_start),
                str(char_end),
                _stable_json(source_locator),
            ]
        )
        candidate_id = uuid5(NAMESPACE_URL, f"orchid-continuum:glossary-candidate:{fingerprint}")
        return self.repository.upsert_candidate(
            {
                "candidate_id": candidate_id,
                "fingerprint": fingerprint,
                "display_term": display_term,
                "normalized_term": normalized_term,
                "language": language.strip() or "und",
                "source_kind": source_kind.strip(),
                "source_hash": source_hash.strip(),
                "source_locator": dict(source_locator),
                "char_start": char_start,
                "char_end": char_end,
                "resolution_state": state.value,
                "matched_concept_id": matched_concept_id,
                "proposed_definition": proposed_definition.strip()
                if proposed_definition and proposed_definition.strip()
                else None,
                "provenance": {
                    **dict(provenance or {}),
                    "concept_resolution": resolution,
                    "automatic_canonical_promotion": False,
                },
                "review_state": "PENDING",
            }
        )

    def list_candidates(
        self, *, resolution_state: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        return self.repository.list_candidates(
            resolution_state=resolution_state, limit=max(1, min(limit, 500))
        )

    def glossary_entry(self, identifier: UUID | str) -> dict[str, Any]:
        concept = self.concept_service.get_concept(identifier)
        concept_id = concept["concept_id"]
        labels = self.concept_service.list_labels(concept_id)
        definitions = self.concept_service.list_definitions(concept_id)
        figures = self.repository.list_figure_requests(concept_id=concept_id, limit=100)
        preferred = [row for row in labels if row.get("label_type") == "PREFERRED"]
        return {
            "concept": concept,
            "preferred_labels": preferred,
            "labels": labels,
            "definitions": definitions,
            "figure_requests": figures,
            "pronunciation": None,
            "pronunciation_status": "NOT_YET_IMPLEMENTED",
            "canonical_source": "oc_concepts",
        }

    def request_figure(
        self,
        *,
        concept_id: UUID,
        request_type: FigureRequestType,
        title: str,
        generation_prompt: str,
        caption: str | None = None,
        priority: int = 50,
        provenance: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.concept_service.get_concept(concept_id)
        clean_title = title.strip()
        clean_prompt = generation_prompt.strip()
        if not clean_title or not clean_prompt:
            raise ValueError("FIGURE_REQUEST_CONTENT_REQUIRED")
        bounded_priority = max(0, min(priority, 100))
        fingerprint = _sha256(
            [str(concept_id), request_type.value, clean_title, clean_prompt]
        )
        request_id = uuid5(NAMESPACE_URL, f"orchid-continuum:figure-request:{fingerprint}")
        return self.repository.upsert_figure_request(
            {
                "request_id": request_id,
                "fingerprint": fingerprint,
                "concept_id": concept_id,
                "request_type": request_type.value,
                "title": clean_title,
                "caption": caption.strip() if caption and caption.strip() else None,
                "generation_prompt": clean_prompt,
                "priority": bounded_priority,
                "provenance": {
                    **dict(provenance or {}),
                    "scientific_evidence": False,
                    "human_review_required": True,
                },
            }
        )

    def list_figure_requests(
        self,
        *,
        concept_id: UUID | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self.repository.list_figure_requests(
            concept_id=concept_id,
            status=status,
            limit=max(1, min(limit, 500)),
        )
