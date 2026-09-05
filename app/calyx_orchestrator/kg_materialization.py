from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

SCHEMA_VERSION = "oc.kg-materialization.v1"
_SOURCE_PRECEDENCE = {
    "canonical_reviewed": 0,
    "canonical_unreviewed": 1,
    "external_discovery": 2,
}
_SENSITIVE_KEYS = {
    "latitude",
    "longitude",
    "lat",
    "lon",
    "lng",
    "coordinates",
    "exact_location",
    "private_locality",
    "credential",
    "credentials",
    "secret",
    "token",
    "api_key",
    "password",
}


class EvidenceState(str, Enum):
    VERIFIED = "VERIFIED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _safe(item)
            for key, item in value.items()
            if str(key).casefold() not in _SENSITIVE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    return value


@dataclass(frozen=True)
class KGMaterializationRecord:
    record_id: str
    source_domain: str
    source_class: str
    evidence_state: EvidenceState
    taxon_id: str | None
    taxon_name: str | None
    predicate: str
    value: Any
    provenance_chain: tuple[dict[str, Any], ...] = ()
    human_review_required: bool = True
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.source_class not in _SOURCE_PRECEDENCE:
            raise ValueError(f"unsupported source_class: {self.source_class}")
        if not self.record_id or not self.source_domain or not self.predicate:
            raise ValueError("record_id, source_domain, and predicate are required")
        if not self.human_review_required:
            raise ValueError("KG materialization records must remain human-review gated")

    @property
    def precedence(self) -> int:
        return _SOURCE_PRECEDENCE[self.source_class]

    def to_dict(self) -> dict[str, Any]:
        return _safe(
            {
                "schema_version": self.schema_version,
                "record_id": self.record_id,
                "source_domain": self.source_domain,
                "source_class": self.source_class,
                "evidence_state": self.evidence_state.value,
                "taxon_binding": {
                    "taxon_id": self.taxon_id,
                    "taxon_name": self.taxon_name,
                },
                "predicate": self.predicate,
                "value": self.value,
                "provenance_chain": list(self.provenance_chain),
                "human_review_required": self.human_review_required,
            }
        )


@dataclass
class KnowledgeGraphPipeline:
    automatic_publication: bool = False
    knowledge_graph_mutation: bool = False
    taxonomy_activation: bool = False
    scientific_publication: bool = False

    def __post_init__(self) -> None:
        if any(
            (
                self.automatic_publication,
                self.knowledge_graph_mutation,
                self.taxonomy_activation,
                self.scientific_publication,
            )
        ):
            raise ValueError("governed KG pipeline cannot grant publication or mutation authority")

    def prepare(self, records: Iterable[KGMaterializationRecord]) -> list[KGMaterializationRecord]:
        """Return deterministic KG-ready candidates without publishing or mutating anything."""
        return sorted(
            records,
            key=lambda item: (
                item.precedence,
                item.source_domain,
                item.taxon_id or "",
                item.predicate,
                item.record_id,
            ),
        )

    def serialize(self, records: Iterable[KGMaterializationRecord]) -> dict[str, Any]:
        prepared = self.prepare(records)
        return {
            "schema_version": SCHEMA_VERSION,
            "automatic_publication": False,
            "knowledge_graph_mutation": False,
            "taxonomy_activation": False,
            "scientific_publication": False,
            "records": [item.to_dict() for item in prepared],
        }


@dataclass
class KGReadThroughGateway:
    available: bool
    records: list[KGMaterializationRecord] = field(default_factory=list)

    def query(self, *, taxon_id: str, predicate: str | None = None) -> dict[str, Any]:
        if not self.available:
            return {
                "schema_version": SCHEMA_VERSION,
                "state": EvidenceState.UNKNOWN.value,
                "reason": "knowledge_graph_unavailable",
                "taxon_id": taxon_id,
                "predicate": predicate,
                "records": None,
                "edge_presence": None,
            }

        matches = [
            item
            for item in self.records
            if item.taxon_id == taxon_id and (predicate is None or item.predicate == predicate)
        ]
        matches.sort(
            key=lambda item: (
                item.precedence,
                item.source_domain,
                item.predicate,
                item.record_id,
            )
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "state": EvidenceState.VERIFIED.value if matches else EvidenceState.UNKNOWN.value,
            "reason": "records_found" if matches else "no_reviewable_records_found",
            "taxon_id": taxon_id,
            "predicate": predicate,
            "records": [item.to_dict() for item in matches],
            "edge_presence": True if matches else None,
        }
