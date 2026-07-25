from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

from .interfaces import ConceptRepository
from .lexical import DefinitionType, LabelType, normalize_lexical_value
from .models import ConceptStatus, ReviewState, concept_uri

_TRANSITIONS: dict[ConceptStatus, set[ConceptStatus]] = {
    ConceptStatus.DRAFT: {ConceptStatus.ACTIVE, ConceptStatus.DEPRECATED},
    ConceptStatus.ACTIVE: {ConceptStatus.DEPRECATED, ConceptStatus.SUPERSEDED},
    ConceptStatus.DEPRECATED: {ConceptStatus.SUPERSEDED},
    ConceptStatus.SUPERSEDED: set(),
}


class ConceptRegistryService:
    def __init__(self, repository: ConceptRepository) -> None:
        self.repository = repository

    def create_scheme(
        self,
        *,
        scheme_key: str,
        name: str,
        authority: str,
        steward: str,
        review_state: ReviewState = ReviewState.PENDING,
    ) -> dict[str, Any]:
        return self.repository.create_scheme(
            {
                "scheme_id": uuid4(),
                "scheme_key": scheme_key,
                "name": name,
                "authority": authority,
                "steward": steward,
                "review_state": review_state.value,
            }
        )

    def create_release(
        self,
        *,
        scheme_id: UUID,
        version: str,
        metadata: Mapping[str, Any] | None = None,
        status: str = "DRAFT",
    ) -> dict[str, Any]:
        if self.repository.get_scheme(scheme_id) is None:
            raise LookupError("CONCEPT_SCHEME_NOT_FOUND")
        return self.repository.create_release(
            {
                "release_id": uuid4(),
                "scheme_id": scheme_id,
                "version": version,
                "status": status,
                "metadata": dict(metadata or {}),
            }
        )

    def create_concept(
        self,
        *,
        scheme_id: UUID,
        steward: str,
        release_id: UUID | None = None,
        concept_id: UUID | None = None,
        review_state: ReviewState = ReviewState.PENDING,
    ) -> dict[str, Any]:
        if self.repository.get_scheme(scheme_id) is None:
            raise LookupError("CONCEPT_SCHEME_NOT_FOUND")
        if release_id is not None:
            release = self.repository.get_release(release_id)
            if release is None or release["scheme_id"] != scheme_id:
                raise ValueError("CONCEPT_RELEASE_SCHEME_MISMATCH")
        opaque_id = concept_id or uuid4()
        return self.repository.create_concept(
            {
                "concept_id": opaque_id,
                "concept_uri": concept_uri(opaque_id),
                "scheme_id": scheme_id,
                "release_id": release_id,
                "status": ConceptStatus.DRAFT.value,
                "review_state": review_state.value,
                "steward": steward,
            }
        )

    def get_concept(self, identifier: UUID | str) -> dict[str, Any]:
        normalized = self.parse_identifier(identifier)
        result = self.repository.get_concept(normalized)
        if result is None:
            raise LookupError("CONCEPT_NOT_FOUND")
        return result

    @staticmethod
    def parse_identifier(identifier: UUID | str) -> UUID | str:
        if isinstance(identifier, UUID):
            return identifier
        value = identifier.strip()
        prefix = "https://id.orchidcontinuum.org/concept/"
        candidate = value.removeprefix(prefix)
        try:
            return UUID(candidate)
        except ValueError:
            if value.startswith(prefix):
                raise ValueError("INVALID_CONCEPT_URI") from None
            raise ValueError("INVALID_CONCEPT_IDENTIFIER") from None

    def transition(
        self,
        concept_id: UUID,
        target_status: ConceptStatus,
        *,
        actor: str,
        superseded_by_id: UUID | None = None,
    ) -> dict[str, Any]:
        current = self.get_concept(concept_id)
        source_status = ConceptStatus(current["status"])
        if target_status not in _TRANSITIONS[source_status]:
            raise ValueError("INVALID_CONCEPT_STATUS_TRANSITION")
        if target_status is ConceptStatus.SUPERSEDED:
            if superseded_by_id is None:
                raise ValueError("SUPERSEDED_CONCEPT_REQUIRES_REPLACEMENT")
            if superseded_by_id == concept_id:
                raise ValueError("CONCEPT_CANNOT_SUPERSEDE_ITSELF")
            replacement = self.get_concept(superseded_by_id)
            if replacement["scheme_id"] != current["scheme_id"]:
                raise ValueError("SUPERSESSION_SCHEME_MISMATCH")
            if replacement["status"] != ConceptStatus.ACTIVE.value:
                raise ValueError("SUPERSESSION_REPLACEMENT_NOT_ACTIVE")
        elif superseded_by_id is not None:
            raise ValueError("REPLACEMENT_ONLY_ALLOWED_FOR_SUPERSESSION")
        review_state = (
            ReviewState.APPROVED.value
            if target_status is ConceptStatus.ACTIVE
            else current["review_state"]
        )
        result = self.repository.transition_concept(
            concept_id,
            target_status.value,
            review_state,
            superseded_by_id,
            actor,
        )
        if result is None:
            raise LookupError("CONCEPT_NOT_FOUND")
        return result

    def create_label(
        self,
        *,
        concept_id: UUID,
        label_type: LabelType,
        label: str,
        actor: str,
        language: str = "und",
        script: str | None = None,
        editorial_context: str = "default",
        provenance: Mapping[str, Any] | None = None,
        review_state: ReviewState = ReviewState.PENDING,
    ) -> dict[str, Any]:
        self.get_concept(concept_id)
        normalized = normalize_lexical_value(label)
        if not normalized:
            raise ValueError("EMPTY_CONCEPT_LABEL")
        return self.repository.create_label(
            {
                "label_id": uuid4(),
                "concept_id": concept_id,
                "label_type": label_type.value,
                "label": label.strip(),
                "normalized_label": normalized,
                "language": language.strip() or "und",
                "script": script,
                "editorial_context": editorial_context.strip() or "default",
                "provenance": dict(provenance or {}),
                "review_state": review_state.value,
                "actor": actor,
            }
        )

    def list_labels(self, identifier: UUID | str) -> list[dict[str, Any]]:
        concept = self.get_concept(identifier)
        return self.repository.list_labels(concept["concept_id"])

    def search_concepts(
        self,
        query: str,
        *,
        language: str | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        normalized = normalize_lexical_value(query)
        if not normalized:
            raise ValueError("EMPTY_CONCEPT_SEARCH_QUERY")
        bounded_limit = max(1, min(limit, 100))
        matches = self.repository.search_labels(
            normalized,
            language=language,
            limit=bounded_limit,
        )
        exact_concept_ids = {
            row["concept_id"]
            for row in matches
            if row["normalized_label"] == normalized
        }
        if not matches:
            resolution = "UNRESOLVED"
        elif len(exact_concept_ids) == 1:
            resolution = "RESOLVED"
        elif len(exact_concept_ids) > 1:
            resolution = "AMBIGUOUS"
        else:
            resolution = "CANDIDATES"
        return {
            "query": query,
            "normalized_query": normalized,
            "resolution": resolution,
            "exact_concept_ids": sorted(str(value) for value in exact_concept_ids),
            "matches": matches,
        }

    def create_definition(
        self,
        *,
        concept_id: UUID,
        definition_type: DefinitionType,
        text: str,
        actor: str,
        language: str = "und",
        script: str | None = None,
        provenance: Mapping[str, Any] | None = None,
        review_state: ReviewState = ReviewState.PENDING,
    ) -> dict[str, Any]:
        self.get_concept(concept_id)
        normalized_text = text.strip()
        if not normalized_text:
            raise ValueError("EMPTY_CONCEPT_DEFINITION")
        return self.repository.create_definition(
            {
                "definition_id": uuid4(),
                "concept_id": concept_id,
                "definition_type": definition_type.value,
                "text": normalized_text,
                "language": language.strip() or "und",
                "script": script,
                "provenance": dict(provenance or {}),
                "review_state": review_state.value,
                "actor": actor,
            }
        )

    def list_definitions(self, identifier: UUID | str) -> list[dict[str, Any]]:
        concept = self.get_concept(identifier)
        return self.repository.list_definitions(concept["concept_id"])


class OntologyTermConceptAdapter:
    """Additive bridge; it never changes an ontology term or its APIs."""

    def __init__(self, repository: ConceptRepository) -> None:
        self.repository = repository

    def adapt(
        self,
        *,
        ontology_term_id: int,
        scheme_id: UUID,
        steward: str,
        actor: str,
        release_id: UUID | None = None,
    ) -> dict[str, Any]:
        opaque_id = uuid4()
        return self.repository.adapt_ontology_term(
            ontology_term_id,
            {
                "concept_id": opaque_id,
                "concept_uri": concept_uri(opaque_id),
                "scheme_id": scheme_id,
                "release_id": release_id,
                "status": ConceptStatus.DRAFT.value,
                "review_state": ReviewState.PENDING.value,
                "steward": steward,
            },
            actor,
        )
