"""Stable Orchid Continuum identifiers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from uuid import UUID, uuid4

from .exceptions import InvalidOCIDError

_OCID_PATTERN = re.compile(r"^OC:(?P<kind>[A-Z][A-Z0-9_]*)\:(?P<value>[0-9a-f]{32})$")


class OCIDKind(str, Enum):
    """Canonical scientific object categories used in OCIDs."""

    SCIENTIFIC_OBJECT = "OBJECT"
    EVIDENCE = "EVIDENCE"
    ASSERTION = "ASSERTION"
    RELATIONSHIP = "RELATIONSHIP"
    KNOWLEDGE_OBJECT = "KNOWLEDGE"
    EVENT = "EVENT"
    PUBLICATION = "PUBLICATION"


@dataclass(frozen=True, slots=True)
class OCID:
    """Immutable, parseable Orchid Continuum identifier."""

    kind: OCIDKind
    value: UUID

    def __str__(self) -> str:
        return f"OC:{self.kind.value}:{self.value.hex}"

    @classmethod
    def parse(cls, raw: str) -> "OCID":
        match = _OCID_PATTERN.fullmatch(str(raw).strip())
        if match is None:
            raise InvalidOCIDError(f"Invalid OCID: {raw!r}")
        try:
            kind = OCIDKind(match.group("kind"))
            value = UUID(hex=match.group("value"))
        except (ValueError, AttributeError) as exc:
            raise InvalidOCIDError(f"Invalid OCID: {raw!r}") from exc
        return cls(kind=kind, value=value)


class OCIDFactory:
    """Creates globally unique OCIDs for kernel objects."""

    @staticmethod
    def new(kind: OCIDKind = OCIDKind.SCIENTIFIC_OBJECT) -> OCID:
        return OCID(kind=kind, value=uuid4())
