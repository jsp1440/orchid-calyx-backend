import hashlib
import re
from collections.abc import Sequence
from typing import Any

from .interfaces import SemanticCandidateRepository, SemanticExtractor
from .models import EntityDraft, EvidenceDraft, ExtractionStage, RelationshipDraft


class RuleBasedSemanticExtractor:
    """Deterministic, provenance-preserving extraction without external calls."""

    _binomial = re.compile(r"\b([A-Z][a-z]{2,}\s+[a-z][a-z-]{2,})\b")
    _relations = re.compile(
        r"\b([A-Z][a-z]{2,}\s+[a-z][a-z-]{2,})\s+"
        r"(is pollinated by|is associated with|occurs in|is a synonym of)\s+"
        r"([A-Z][A-Za-z-]*(?:\s+[a-z][a-z-]{2,})?)\b",
        re.IGNORECASE,
    )
    _predicate = {
        "is pollinated by": "POLLINATED_BY",
        "is associated with": "ASSOCIATED_WITH",
        "occurs in": "OCCURS_IN",
        "is a synonym of": "SYNONYM_OF",
    }

    def extract_entities(self, text: str) -> list[EntityDraft]:
        entities: list[EntityDraft] = []
        seen: set[tuple[str, str]] = set()
        for match in self._binomial.finditer(text):
            name = match.group(1)
            key = ("TAXON", name.casefold())
            if key not in seen:
                seen.add(key)
                entities.append(EntityDraft("TAXON", name, name.casefold(), 0.92, match.start(1), match.end(1)))
        for relation in self._relations.finditer(text):
            name = relation.group(3)
            entity_type = "TAXON" if " " in name else "CONCEPT"
            key = (entity_type, name.casefold())
            if key not in seen:
                seen.add(key)
                entities.append(EntityDraft(entity_type, name, name.casefold(), 0.78, relation.start(3), relation.end(3)))
        return entities

    def extract_relationships(self, text: str, entities: Sequence[EntityDraft]) -> list[RelationshipDraft]:
        index = {entity.normalized_name: position for position, entity in enumerate(entities)}
        relationships: list[RelationshipDraft] = []
        for match in self._relations.finditer(text):
            subject = index.get(match.group(1).casefold())
            object_ = index.get(match.group(3).casefold())
            if subject is None or object_ is None:
                continue
            relationships.append(RelationshipDraft(subject, self._predicate[match.group(2).lower()], object_, 0.86, match.start(), match.end()))
        return relationships

    def build_evidence(self, text: str, sha256: str, relationships: Sequence[RelationshipDraft], document_id: int) -> list[EvidenceDraft]:
        return [
            EvidenceDraft(
                "TEXT_SPAN",
                text[item.start_offset:item.end_offset],
                item.start_offset,
                item.end_offset,
                sha256,
                {"document_id": document_id, "extractor": "rule-based-v1", "content_sha256": sha256},
            )
            for item in relationships
        ]


class ExtractionOrchestrationService:
    def __init__(self, repository: SemanticCandidateRepository, extractor: SemanticExtractor) -> None:
        self._repository = repository
        self._extractor = extractor

    def extract(self, document_id: int, actor: str) -> dict[str, Any]:
        document = self._repository.load_document(document_id)
        if document is None:
            raise LookupError("DOCUMENT_NOT_FOUND")
        text = document.get("extracted_text")
        hash_input = text if isinstance(text, str) else ""
        sha256 = str(document.get("sha256") or hashlib.sha256(hash_input.encode("utf-8")).hexdigest())
        session = self._repository.create_session(
            document_id,
            actor,
            {"document_id": document_id, "content_sha256": sha256, "extractor": "rule-based-v1"},
        )
        session_id = int(session["id"])
        try:
            if not isinstance(text, str) or not text.strip():
                raise ValueError("DOCUMENT_TEXT_NOT_AVAILABLE")
            self._repository.transition_session(session_id, ExtractionStage.PARSING, actor)
            normalized_text = text.replace("\x00", "").strip()
            self._repository.transition_session(session_id, ExtractionStage.ENTITY_EXTRACTION, actor)
            entities = self._extractor.extract_entities(normalized_text)
            self._repository.transition_session(session_id, ExtractionStage.RELATIONSHIP_EXTRACTION, actor)
            relationships = self._extractor.extract_relationships(normalized_text, entities)
            self._repository.transition_session(session_id, ExtractionStage.EVIDENCE_GENERATION, actor)
            evidence = self._extractor.build_evidence(normalized_text, sha256, relationships, document_id)
            if len(evidence) != len(relationships):
                raise ValueError("RELATIONSHIP_EVIDENCE_INCOMPLETE")
            self._repository.transition_session(session_id, ExtractionStage.CANDIDATE_GENERATION, actor)
            self._repository.save_candidates(session_id, entities, relationships, evidence, actor)
            return self._repository.transition_session(session_id, ExtractionStage.READY_FOR_REVIEW, actor)
        except Exception as exc:
            self._repository.transition_session(session_id, ExtractionStage.FAILED, actor, str(exc)[:2000])
            raise


def candidate_changes(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {"name", "entity_type", "predicate", "confidence", "review_status"}
    changes = {key: value for key, value in payload.items() if key in allowed and value is not None}
    if not changes:
        raise ValueError("NO_CANDIDATE_CHANGES")
    return changes
