from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def stable_checksum(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# BUILD-ATLAS-405 — temporal change detection
class TemporalLayerSnapshot(StrictModel):
    snapshot_id: str
    layer_id: str
    observed_at: datetime
    metric_value: float
    evidence_ids: list[str] = Field(min_length=1)


class TemporalChangeResult(StrictModel):
    layer_id: str
    earlier_snapshot_id: str
    later_snapshot_id: str
    absolute_change: float
    percent_change: float | None
    evidence_ids: list[str]
    status: Literal["candidate"] = "candidate"


def detect_temporal_change(earlier: TemporalLayerSnapshot, later: TemporalLayerSnapshot) -> TemporalChangeResult:
    if earlier.layer_id != later.layer_id:
        raise ValueError("temporal snapshots must reference the same layer")
    if earlier.observed_at >= later.observed_at:
        raise ValueError("later snapshot must occur after earlier snapshot")
    change = later.metric_value - earlier.metric_value
    percent = None if earlier.metric_value == 0 else (change / earlier.metric_value) * 100
    return TemporalChangeResult(
        layer_id=earlier.layer_id,
        earlier_snapshot_id=earlier.snapshot_id,
        later_snapshot_id=later.snapshot_id,
        absolute_change=round(change, 8),
        percent_change=None if percent is None else round(percent, 8),
        evidence_ids=sorted(set(earlier.evidence_ids + later.evidence_ids)),
    )


# BUILD-RS-502 — governed experiment runs
class ExperimentRun(StrictModel):
    run_id: str
    protocol_id: str
    protocol_checksum: str = Field(min_length=64, max_length=64)
    input_artifact_ids: list[str] = Field(min_length=1)
    started_at: datetime
    completed_at: datetime | None = None
    output_artifact_ids: list[str] = Field(default_factory=list)
    status: Literal["running", "completed", "failed"] = "running"

    def complete(self, completed_at: datetime, output_artifact_ids: list[str]) -> "ExperimentRun":
        if self.status != "running":
            raise ValueError("only running experiments may complete")
        if completed_at <= self.started_at:
            raise ValueError("completion must occur after start")
        if not output_artifact_ids:
            raise ValueError("completed experiments require output artifacts")
        return self.model_copy(update={
            "completed_at": completed_at,
            "output_artifact_ids": sorted(set(output_artifact_ids)),
            "status": "completed",
        })


# BUILD-CON-602 — inventory import staging
class InventoryRow(StrictModel):
    row_number: int = Field(ge=1)
    accession_number: str
    taxon_name: str
    location: str
    source: str


class InventoryImportResult(StrictModel):
    accepted: list[InventoryRow]
    rejected_rows: list[int]
    checksum: str = Field(min_length=64, max_length=64)
    committed: bool = False


def stage_inventory_import(rows: list[InventoryRow]) -> InventoryImportResult:
    seen: set[str] = set()
    accepted: list[InventoryRow] = []
    rejected: list[int] = []
    for row in sorted(rows, key=lambda item: item.row_number):
        key = row.accession_number.casefold().strip()
        if not key or key in seen or not row.taxon_name.strip() or not row.location.strip():
            rejected.append(row.row_number)
            continue
        seen.add(key)
        accepted.append(row)
    checksum = stable_checksum([item.model_dump(mode="json") for item in accepted])
    return InventoryImportResult(accepted=accepted, rejected_rows=rejected, checksum=checksum)


# BUILD-MATRIX-702 — deterministic identification key generation
class KeyCharacter(StrictModel):
    character_id: str
    question: str
    state_to_taxa: dict[str, list[str]]


class IdentificationKeyStep(StrictModel):
    step_number: int
    character_id: str
    question: str
    branches: dict[str, list[str]]


def generate_identification_key(characters: list[KeyCharacter]) -> list[IdentificationKeyStep]:
    if not characters:
        raise ValueError("at least one character is required")
    ordered = sorted(
        characters,
        key=lambda item: (-len(item.state_to_taxa), item.character_id),
    )
    return [
        IdentificationKeyStep(
            step_number=index,
            character_id=item.character_id,
            question=item.question,
            branches={state: sorted(set(taxa)) for state, taxa in sorted(item.state_to_taxa.items())},
        )
        for index, item in enumerate(ordered, start=1)
    ]


# BUILD-VISION-802 — governed annotation sets
class ImageAnnotation(StrictModel):
    annotation_id: str
    image_id: str
    label: str
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)
    evidence_id: str


class AnnotationSet(StrictModel):
    set_id: str
    image_id: str
    version: int = Field(ge=1)
    annotations: list[ImageAnnotation] = Field(min_length=1)
    reviewer_status: Literal["candidate", "approved", "rejected"] = "candidate"
    checksum: str


def build_annotation_set(set_id: str, image_id: str, version: int, annotations: list[ImageAnnotation]) -> AnnotationSet:
    if any(item.image_id != image_id for item in annotations):
        raise ValueError("all annotations must reference the annotation-set image")
    ids = [item.annotation_id for item in annotations]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate annotation IDs")
    ordered = sorted(annotations, key=lambda item: item.annotation_id)
    return AnnotationSet(
        set_id=set_id,
        image_id=image_id,
        version=version,
        annotations=ordered,
        checksum=stable_checksum([item.model_dump(mode="json") for item in ordered]),
    )


# BUILD-PUB-902 — citation manifest generation
class CitationRecord(StrictModel):
    citation_id: str
    title: str
    source_uri: str
    license: str
    accessed_at: datetime


class CitationManifest(StrictModel):
    citation_ids: list[str]
    records: list[CitationRecord]
    checksum: str


def build_citation_manifest(records: list[CitationRecord]) -> CitationManifest:
    if not records:
        raise ValueError("citation manifest requires at least one record")
    ids = [item.citation_id for item in records]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate citation IDs")
    ordered = sorted(records, key=lambda item: item.citation_id)
    return CitationManifest(
        citation_ids=[item.citation_id for item in ordered],
        records=ordered,
        checksum=stable_checksum([item.model_dump(mode="json") for item in ordered]),
    )


# BUILD-INT-952 — event replay protection
class EventReplayLedger:
    def __init__(self) -> None:
        self._checksums: dict[str, str] = {}

    def accept(self, event_id: str, payload: dict[str, object]) -> bool:
        checksum = stable_checksum(payload)
        existing = self._checksums.get(event_id)
        if existing is None:
            self._checksums[event_id] = checksum
            return True
        if existing != checksum:
            raise ValueError("event replay payload conflicts with prior event identity")
        return False


# BUILD-MC-203 — SLA and stale-work health
class WorkHealthRecord(StrictModel):
    work_id: str
    status: Literal["queued", "running", "blocked", "completed"]
    updated_at: datetime
    sla_minutes: int = Field(gt=0)


class WorkHealthSummary(StrictModel):
    stale_ids: list[str]
    blocked_ids: list[str]
    healthy_count: int = Field(ge=0)


def summarize_work_health(records: list[WorkHealthRecord], now: datetime) -> WorkHealthSummary:
    if now.tzinfo is None:
        raise ValueError("health summary requires timezone-aware current time")
    stale: list[str] = []
    blocked: list[str] = []
    healthy = 0
    for item in records:
        age_minutes = (now - item.updated_at).total_seconds() / 60
        if item.status == "blocked":
            blocked.append(item.work_id)
        if item.status != "completed" and age_minutes > item.sla_minutes:
            stale.append(item.work_id)
        else:
            healthy += 1
    return WorkHealthSummary(stale_ids=sorted(stale), blocked_ids=sorted(blocked), healthy_count=healthy)


# BUILD-BRAIN-115 — living design-manual generation
class DesignManualSection(StrictModel):
    section_id: str
    title: str
    object_ids: list[str] = Field(min_length=1)


class DesignManual(StrictModel):
    manual_id: str
    architecture_id: str
    sections: list[DesignManualSection]
    generated_at: datetime
    checksum: str
    publication_enabled: bool = False


def generate_design_manual(architecture_id: str, sections: list[DesignManualSection], generated_at: datetime) -> DesignManual:
    if generated_at.tzinfo is None:
        raise ValueError("design manual timestamps must be timezone-aware")
    ids = [item.section_id for item in sections]
    if not sections or len(ids) != len(set(ids)):
        raise ValueError("design manual sections must be non-empty and uniquely identified")
    ordered = sorted(sections, key=lambda item: item.section_id)
    checksum = stable_checksum([item.model_dump(mode="json") for item in ordered])
    return DesignManual(
        manual_id=f"manual:{architecture_id}",
        architecture_id=architecture_id,
        sections=ordered,
        generated_at=generated_at,
        checksum=checksum,
    )


# BUILD-INT-953 — integration contract readiness
class IntegrationContract(StrictModel):
    contract_id: str
    producer: str
    consumer: str
    event_type: str
    schema_version: str
    required_evidence_ids: list[str] = Field(min_length=1)
    enabled: bool = False


class IntegrationReadiness(StrictModel):
    ready_contract_ids: list[str]
    blocked_contract_ids: list[str]
    all_ready: bool


def assess_integration_readiness(contracts: list[IntegrationContract]) -> IntegrationReadiness:
    ready = sorted(item.contract_id for item in contracts if item.enabled and item.required_evidence_ids)
    blocked = sorted(item.contract_id for item in contracts if item.contract_id not in ready)
    return IntegrationReadiness(ready_contract_ids=ready, blocked_contract_ids=blocked, all_ready=bool(contracts) and not blocked)
