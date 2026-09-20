"""Read-only projection of reviewed canonical concepts as glossary entries."""

from __future__ import annotations

from typing import Any

from app.concepts.services import ConceptRegistryService


class GlossaryProjectionNotReviewedError(ValueError):
    """The concept has not crossed the canonical review boundary."""


def project_canonical_glossary_entry(
    service: ConceptRegistryService,
    identifier: str,
    *,
    language: str | None = None,
) -> dict[str, Any]:
    """Project existing approved registry content without creating new science."""
    concept = service.get_concept(identifier)
    if concept.get("status") != "ACTIVE" or concept.get("review_state") != "APPROVED":
        raise GlossaryProjectionNotReviewedError(
            "CANONICAL_GLOSSARY_CONCEPT_NOT_APPROVED"
        )

    labels = [
        row
        for row in service.list_labels(identifier)
        if row.get("review_state") == "APPROVED"
        and (language is None or row.get("language") == language)
    ]
    definitions = [
        row
        for row in service.list_definitions(identifier)
        if row.get("review_state") == "APPROVED"
        and (language is None or row.get("language") == language)
    ]
    labels.sort(
        key=lambda row: (
            row.get("label_type") != "PREFERRED",
            str(row.get("normalized_label", "")),
            str(row.get("label_id", "")),
        )
    )
    definitions.sort(
        key=lambda row: (
            str(row.get("definition_type", "")),
            str(row.get("language", "")),
            str(row.get("definition_id", "")),
        )
    )
    definitions_by_audience: dict[str, list[dict[str, Any]]] = {}
    for definition in definitions:
        definitions_by_audience.setdefault(
            str(definition.get("definition_type")), []
        ).append(definition)

    return {
        "contract": "calyx-canonical-glossary-projection-v1",
        "concept": concept,
        "labels": labels,
        "definitions_by_audience": definitions_by_audience,
        "language_filter": language,
        "source": "app.concepts",
        "read_only": True,
        "reviewed_content_only": True,
        "definition_invention_authorized": False,
        "canonical_mutation_authorized": False,
        "knowledge_graph_publication_authorized": False,
    }
