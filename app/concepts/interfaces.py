from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID


class ConceptRepository(Protocol):
    def create_scheme(self, data: Mapping[str, Any]) -> dict[str, Any]: ...

    def get_scheme(self, scheme_id: UUID) -> dict[str, Any] | None: ...

    def create_release(self, data: Mapping[str, Any]) -> dict[str, Any]: ...

    def get_release(self, release_id: UUID) -> dict[str, Any] | None: ...

    def create_concept(self, data: Mapping[str, Any]) -> dict[str, Any]: ...

    def get_concept(self, identifier: UUID | str) -> dict[str, Any] | None: ...

    def transition_concept(
        self,
        concept_id: UUID,
        status: str,
        review_state: str,
        superseded_by_id: UUID | None,
        actor: str,
    ) -> dict[str, Any] | None: ...

    def adapt_ontology_term(
        self,
        term_id: int,
        concept_data: Mapping[str, Any],
        actor: str,
    ) -> dict[str, Any]: ...

    def create_label(self, data: Mapping[str, Any]) -> dict[str, Any]: ...

    def list_labels(self, concept_id: UUID) -> list[dict[str, Any]]: ...

    def search_labels(
        self,
        normalized_query: str,
        *,
        language: str | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]: ...

    def create_definition(self, data: Mapping[str, Any]) -> dict[str, Any]: ...

    def list_definitions(self, concept_id: UUID) -> list[dict[str, Any]]: ...
