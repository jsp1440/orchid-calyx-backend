from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class ArtifactRelationType(StrEnum):
    DERIVED_FROM = "derived_from"
    EVIDENCES = "evidences"
    RECEIPT_FOR = "receipt_for"
    SUPERSEDES = "supersedes"


@dataclass(frozen=True, slots=True)
class ArtifactRegistration:
    artifact_id: str
    content: bytes
    media_type: str
    source_uri: str
    producer_assignment_id: str
    license: str | None = None
    evidence_uris: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    def validate(self) -> None:
        if not self.artifact_id.strip():
            raise ValueError("ARTIFACT_ID_REQUIRED")
        if not self.content:
            raise ValueError("ARTIFACT_CONTENT_REQUIRED")
        if "/" not in self.media_type:
            raise ValueError("ARTIFACT_MEDIA_TYPE_INVALID")
        _require_uri(self.source_uri, "ARTIFACT_SOURCE_URI_INVALID")
        if not self.producer_assignment_id.strip():
            raise ValueError("PRODUCER_ASSIGNMENT_REQUIRED")
        for uri in self.evidence_uris:
            _require_uri(uri, "EVIDENCE_URI_INVALID")


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    artifact_id: str
    checksum: str
    byte_length: int
    media_type: str
    source_uri: str
    producer_assignment_id: str
    license: str | None
    evidence_uris: tuple[str, ...]
    metadata: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ArtifactRelation:
    source_artifact_id: str
    relation: ArtifactRelationType
    target_artifact_id: str


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    record: ArtifactRecord
    duplicate_content_of: str | None = None
    created: bool = True


class ImmutableArtifactRegistry:
    """Immutable metadata and lineage registry; never a publication authority."""

    def __init__(self) -> None:
        self._records: dict[str, ArtifactRecord] = {}
        self._by_checksum: dict[str, str] = {}
        self._relations: set[ArtifactRelation] = set()

    def register(self, registration: ArtifactRegistration) -> RegistrationResult:
        registration.validate()
        existing = self._records.get(registration.artifact_id)
        if existing is not None:
            candidate = self._to_record(registration)
            if existing != candidate:
                raise ValueError("IMMUTABLE_ARTIFACT_CONFLICT")
            return RegistrationResult(record=existing, created=False)
        record = self._to_record(registration)
        duplicate = self._by_checksum.get(record.checksum)
        self._records[record.artifact_id] = record
        self._by_checksum.setdefault(record.checksum, record.artifact_id)
        return RegistrationResult(record=record, duplicate_content_of=duplicate)

    def relate(self, *, source_artifact_id: str, relation: ArtifactRelationType | str, target_artifact_id: str) -> ArtifactRelation:
        if source_artifact_id == target_artifact_id:
            raise ValueError("ARTIFACT_SELF_RELATION")
        self.require(source_artifact_id)
        self.require(target_artifact_id)
        normalized = relation if isinstance(relation, ArtifactRelationType) else ArtifactRelationType(relation)
        edge = ArtifactRelation(source_artifact_id, normalized, target_artifact_id)
        self._relations.add(edge)
        return edge

    def require_evidence(self, artifact_id: str) -> ArtifactRecord:
        record = self.require(artifact_id)
        linked = any(edge.source_artifact_id == artifact_id and edge.relation == ArtifactRelationType.EVIDENCES for edge in self._relations)
        if not record.evidence_uris and not linked:
            raise ValueError("ARTIFACT_EVIDENCE_REQUIRED")
        return record

    def require(self, artifact_id: str) -> ArtifactRecord:
        try:
            return self._records[artifact_id]
        except KeyError as exc:
            raise LookupError("ARTIFACT_NOT_FOUND") from exc

    def discover(self, *, producer_assignment_id: str | None = None, media_type: str | None = None, checksum: str | None = None, source_uri: str | None = None) -> tuple[ArtifactRecord, ...]:
        records: Iterable[ArtifactRecord] = self._records.values()
        if producer_assignment_id is not None:
            records = (item for item in records if item.producer_assignment_id == producer_assignment_id)
        if media_type is not None:
            records = (item for item in records if item.media_type == media_type)
        if checksum is not None:
            records = (item for item in records if item.checksum == checksum)
        if source_uri is not None:
            records = (item for item in records if item.source_uri == source_uri)
        return tuple(sorted(records, key=lambda item: item.artifact_id))

    def lineage(self, artifact_id: str) -> tuple[ArtifactRelation, ...]:
        self.require(artifact_id)
        return tuple(sorted((edge for edge in self._relations if artifact_id in {edge.source_artifact_id, edge.target_artifact_id}), key=lambda edge: (edge.source_artifact_id, edge.relation.value, edge.target_artifact_id)))

    def snapshot(self) -> dict[str, object]:
        return {"artifact_count": len(self._records), "unique_content_count": len(self._by_checksum), "relation_count": len(self._relations), "artifacts": [{"artifact_id": record.artifact_id, "checksum": record.checksum, "byte_length": record.byte_length, "media_type": record.media_type, "source_uri": record.source_uri, "producer_assignment_id": record.producer_assignment_id, "license": record.license, "evidence_uris": list(record.evidence_uris)} for record in self.discover()]}

    @staticmethod
    def _to_record(registration: ArtifactRegistration) -> ArtifactRecord:
        return ArtifactRecord(artifact_id=registration.artifact_id, checksum=registration.checksum, byte_length=len(registration.content), media_type=registration.media_type, source_uri=registration.source_uri, producer_assignment_id=registration.producer_assignment_id, license=registration.license, evidence_uris=_dedupe(registration.evidence_uris), metadata=dict(registration.metadata))


def _require_uri(value: str, code: str) -> None:
    normalized = value.strip()
    if not normalized or ":" not in normalized:
        raise ValueError(code)


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    output: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized not in output:
            output.append(normalized)
    return tuple(output)
