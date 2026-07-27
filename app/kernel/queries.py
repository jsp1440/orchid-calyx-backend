"""Scientific query contracts and immutable query models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .exceptions import ScientificObjectValidationError
from .identity import OCID, OCIDKind


class QueryObjectType(str, Enum):
    """Canonical object categories supported by scientific queries."""

    SCIENTIFIC_OBJECT = "scientific_object"
    EVIDENCE = "evidence"
    ASSERTION = "assertion"
    RELATIONSHIP = "relationship"
    PUBLICATION = "publication"
    KNOWLEDGE_OBJECT = "knowledge_object"
    EVENT = "event"


class QuerySortDirection(str, Enum):
    """Sort direction for query result ordering."""

    ASCENDING = "ascending"
    DESCENDING = "descending"


@dataclass(frozen=True, slots=True)
class QuerySort:
    """Immutable sort specification for scientific query results."""

    field_name: str
    direction: QuerySortDirection = QuerySortDirection.ASCENDING

    def __post_init__(self) -> None:
        field_name = self.field_name.strip()
        if not field_name:
            raise ScientificObjectValidationError("query sort field_name must not be empty")
        object.__setattr__(self, "field_name", field_name)


@dataclass(frozen=True, slots=True)
class ScientificQuery:
    """Immutable, bounded query specification across Kernel scientific objects."""

    object_types: tuple[QueryObjectType, ...] = field(default_factory=tuple)
    ocids: tuple[OCID, ...] = field(default_factory=tuple)
    linked_ocid: OCID | None = None
    statuses: tuple[str, ...] = field(default_factory=tuple)
    predicates: tuple[str, ...] = field(default_factory=tuple)
    text: str | None = None
    filters: Mapping[str, Any] = field(default_factory=dict)
    sort: tuple[QuerySort, ...] = field(default_factory=tuple)
    limit: int = 100
    offset: int = 0
    include_superseded: bool = False

    def __post_init__(self) -> None:
        object_types = tuple(self.object_types)
        ocids = tuple(self.ocids)
        statuses = tuple(value.strip() for value in self.statuses)
        predicates = tuple(value.strip() for value in self.predicates)
        sort = tuple(self.sort)
        text = self.text.strip() if self.text is not None else None

        if len(set(object_types)) != len(object_types):
            raise ScientificObjectValidationError("query object_types must be unique")
        if len(set(ocids)) != len(ocids):
            raise ScientificObjectValidationError("query ocids must be unique")
        if any(not value for value in statuses):
            raise ScientificObjectValidationError("query statuses must not contain empty values")
        if len(set(statuses)) != len(statuses):
            raise ScientificObjectValidationError("query statuses must be unique")
        if any(not value for value in predicates):
            raise ScientificObjectValidationError("query predicates must not contain empty values")
        if len(set(predicates)) != len(predicates):
            raise ScientificObjectValidationError("query predicates must be unique")
        if self.limit < 1 or self.limit > 1000:
            raise ScientificObjectValidationError("query limit must be between 1 and 1000")
        if self.offset < 0:
            raise ScientificObjectValidationError("query offset must not be negative")
        if any(ocid.kind is OCIDKind.EVENT for ocid in ocids) and (
            object_types and QueryObjectType.EVENT not in object_types
        ):
            raise ScientificObjectValidationError(
                "EVENT OCIDs require EVENT in query object_types when object_types are specified"
            )

        object.__setattr__(self, "object_types", object_types)
        object.__setattr__(self, "ocids", ocids)
        object.__setattr__(self, "statuses", statuses)
        object.__setattr__(self, "predicates", predicates)
        object.__setattr__(self, "sort", sort)
        object.__setattr__(self, "text", text or None)
        object.__setattr__(self, "filters", MappingProxyType(dict(self.filters)))

    @property
    def is_unfiltered(self) -> bool:
        """Return whether this query has no selectors beyond pagination settings."""

        return not any(
            (
                self.object_types,
                self.ocids,
                self.linked_ocid,
                self.statuses,
                self.predicates,
                self.text,
                self.filters,
            )
        )


@dataclass(frozen=True, slots=True)
class QueryPage:
    """Immutable page of scientific query results."""

    items: tuple[Any, ...] = field(default_factory=tuple)
    total: int = 0
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        items = tuple(self.items)
        if self.total < 0:
            raise ScientificObjectValidationError("query page total must not be negative")
        if self.limit < 1 or self.limit > 1000:
            raise ScientificObjectValidationError("query page limit must be between 1 and 1000")
        if self.offset < 0:
            raise ScientificObjectValidationError("query page offset must not be negative")
        if self.total < len(items):
            raise ScientificObjectValidationError("query page total cannot be smaller than item count")
        object.__setattr__(self, "items", items)

    @property
    def has_more(self) -> bool:
        """Return whether another result page follows this one."""

        return self.offset + len(self.items) < self.total
