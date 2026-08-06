from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def stable_checksum(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# BUILD-KE-306 — accessible glossary media selection
class GlossaryMediaCandidate(StrictModel):
    asset_id: str
    media_type: Literal["photograph", "illustration", "diagram", "animation"]
    evidence_ids: list[str] = Field(min_length=1)
    alt_text: str = Field(min_length=5)
    license: str = Field(min_length=2)
    relevance_score: float = Field(ge=0, le=1)
    accessibility_score: float = Field(ge=0, le=1)


class GlossaryMediaSelection(StrictModel):
    concept_id: str
    selected_asset_ids: list[str]
    checksum: str


def select_glossary_media(concept_id: str, candidates: list[GlossaryMediaCandidate], limit: int = 4) -> GlossaryMediaSelection:
    if limit < 1:
        raise ValueError("media-selection limit must be positive")
    ids = [item.asset_id for item in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate glossary media asset IDs")
    ordered = sorted(
        candidates,
        key=lambda item: (-(item.relevance_score + item.accessibility_score), item.media_type, item.asset_id),
    )[:limit]
    selected = [item.asset_id for item in ordered]
    return GlossaryMediaSelection(concept_id=concept_id, selected_asset_ids=selected, checksum=stable_checksum(selected))


# BUILD-ATLAS-407 — sampling-gap analysis
class SamplingCell(StrictModel):
    cell_id: str
    occurrence_count: int = Field(ge=0)
    effort_score: float = Field(ge=0, le=1)
    suitability_score: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(min_length=1)


class SamplingGap(StrictModel):
    cell_id: str
    gap_score: float = Field(ge=0, le=1)
    evidence_ids: list[str]
    status: Literal["candidate"] = "candidate"


def rank_sampling_gaps(cells: list[SamplingCell]) -> list[SamplingGap]:
    results = []
    for cell in cells:
        observation_penalty = 1 / (1 + cell.occurrence_count)
        gap = cell.suitability_score * (1 - cell.effort_score) * observation_penalty
        results.append(SamplingGap(cell_id=cell.cell_id, gap_score=round(gap, 8), evidence_ids=sorted(set(cell.evidence_ids))))
    return sorted(results, key=lambda item: (-item.gap_score, item.cell_id))


# BUILD-RS-504 — provenance notebook manifest
class NotebookCell(StrictModel):
    cell_id: str
    cell_type: Literal["code", "markdown"]
    source_checksum: str = Field(min_length=64, max_length=64)
    input_artifact_ids: list[str] = Field(default_factory=list)
    output_artifact_ids: list[str] = Field(default_factory=list)


class ProvenanceNotebook(StrictModel):
    notebook_id: str
    environment_checksum: str = Field(min_length=64, max_length=64)
    cells: list[NotebookCell] = Field(min_length=1)
    checksum: str
    execution_enabled: bool = False


def build_provenance_notebook(notebook_id: str, environment_checksum: str, cells: list[NotebookCell]) -> ProvenanceNotebook:
    ids = [item.cell_id for item in cells]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate notebook cell IDs")
    ordered = sorted(cells, key=lambda item: item.cell_id)
    checksum = stable_checksum({"environment": environment_checksum, "cells": [item.model_dump(mode="json") for item in ordered]})
    return ProvenanceNotebook(notebook_id=notebook_id, environment_checksum=environment_checksum, cells=ordered, checksum=checksum)


# BUILD-CON-604 — bloom and image history
class BloomRecord(StrictModel):
    bloom_id: str
    specimen_id: str
    opened_at: datetime
    ended_at: datetime | None = None
    image_asset_ids: list[str] = Field(default_factory=list)
    flower_count: int | None = Field(default=None, ge=1)
    notes: str = ""


class BloomHistory:
    def __init__(self) -> None:
        self._records: dict[str, BloomRecord] = {}

    def register(self, record: BloomRecord) -> BloomRecord:
        if record.ended_at is not None and record.ended_at <= record.opened_at:
            raise ValueError("bloom end must occur after opening")
        existing = self._records.get(record.bloom_id)
        if existing and existing != record:
            raise ValueError("conflicting bloom record identity")
        self._records[record.bloom_id] = record
        return record

    def for_specimen(self, specimen_id: str) -> list[BloomRecord]:
        return sorted([item for item in self._records.values() if item.specimen_id == specimen_id], key=lambda item: (item.opened_at, item.bloom_id))


# BUILD-MATRIX-704 — confidence calibration
class CalibrationObservation(StrictModel):
    prediction_id: str
    confidence: float = Field(ge=0, le=1)
    correct: bool


class CalibrationBucket(StrictModel):
    lower_bound: float
    upper_bound: float
    count: int
    mean_confidence: float
    observed_accuracy: float


def calibrate_confidence(observations: list[CalibrationObservation], bucket_width: float = 0.2) -> list[CalibrationBucket]:
    if not 0 < bucket_width <= 1:
        raise ValueError("bucket width must be within (0, 1]")
    buckets: dict[int, list[CalibrationObservation]] = defaultdict(list)
    for item in observations:
        index = min(int(item.confidence / bucket_width), int(1 / bucket_width) - 1)
        buckets[index].append(item)
    results = []
    for index in sorted(buckets):
        values = buckets[index]
        lower = round(index * bucket_width, 8)
        upper = round(min(1.0, lower + bucket_width), 8)
        results.append(CalibrationBucket(
            lower_bound=lower,
            upper_bound=upper,
            count=len(values),
            mean_confidence=round(sum(item.confidence for item in values) / len(values), 8),
            observed_accuracy=round(sum(item.correct for item in values) / len(values), 8),
        ))
    return results


# BUILD-VISION-804 — herbarium interpretation candidates
class HerbariumInterpretation(StrictModel):
    interpretation_id: str
    image_id: str
    proposed_taxon_id: str | None = None
    label_transcription: str | None = None
    proposed_date: str | None = None
    proposed_locality: str | None = None
    evidence_region_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    status: Literal["candidate"] = "candidate"


def validate_herbarium_interpretation(item: HerbariumInterpretation) -> HerbariumInterpretation:
    if not any([item.proposed_taxon_id, item.label_transcription, item.proposed_date, item.proposed_locality]):
        raise ValueError("herbarium interpretation requires at least one proposed field")
    return item


# BUILD-PUB-904 — grant package assembler
class GrantSection(StrictModel):
    section_id: str
    title: str
    body: str
    evidence_ids: list[str] = Field(min_length=1)


class GrantPackage(StrictModel):
    package_id: str
    funder: str
    opportunity_id: str
    sections: list[GrantSection]
    checksum: str
    submission_enabled: bool = False


def assemble_grant_package(package_id: str, funder: str, opportunity_id: str, sections: list[GrantSection]) -> GrantPackage:
    required = {"need", "objectives", "methods", "outcomes", "budget"}
    section_ids = {item.section_id for item in sections}
    missing = sorted(required - section_ids)
    if missing:
        raise ValueError(f"missing required grant sections: {', '.join(missing)}")
    ordered = sorted(sections, key=lambda item: item.section_id)
    return GrantPackage(
        package_id=package_id,
        funder=funder,
        opportunity_id=opportunity_id,
        sections=ordered,
        checksum=stable_checksum([item.model_dump(mode="json") for item in ordered]),
    )


# BUILD-INT-955 — event-schema compatibility
class EventSchema(StrictModel):
    event_type: str
    version: int = Field(ge=1)
    required_fields: set[str] = Field(min_length=1)
    optional_fields: set[str] = Field(default_factory=set)


class SchemaCompatibility(StrictModel):
    compatible: bool
    missing_required_fields: list[str]
    removed_fields: list[str]


def assess_schema_compatibility(previous: EventSchema, candidate: EventSchema) -> SchemaCompatibility:
    if previous.event_type != candidate.event_type:
        raise ValueError("event schemas must describe the same event type")
    if candidate.version <= previous.version:
        raise ValueError("candidate schema version must increase")
    missing = sorted(previous.required_fields - (candidate.required_fields | candidate.optional_fields))
    removed = sorted((previous.required_fields | previous.optional_fields) - (candidate.required_fields | candidate.optional_fields))
    return SchemaCompatibility(compatible=not missing, missing_required_fields=missing, removed_fields=removed)


# BUILD-MC-205 — critical-path projection
class CriticalPathBuild(StrictModel):
    build_id: str
    duration_units: int = Field(gt=0)
    dependency_ids: list[str] = Field(default_factory=list)


class CriticalPathResult(StrictModel):
    ordered_build_ids: list[str]
    total_duration_units: int


def calculate_critical_path(builds: list[CriticalPathBuild]) -> CriticalPathResult:
    by_id = {item.build_id: item for item in builds}
    if len(by_id) != len(builds):
        raise ValueError("duplicate build IDs")
    indegree = {item.build_id: 0 for item in builds}
    children: dict[str, list[str]] = defaultdict(list)
    for item in builds:
        for dependency_id in item.dependency_ids:
            if dependency_id not in by_id:
                raise ValueError(f"missing build dependency: {dependency_id}")
            indegree[item.build_id] += 1
            children[dependency_id].append(item.build_id)
    queue = deque(sorted(build_id for build_id, degree in indegree.items() if degree == 0))
    distance: dict[str, int] = {build_id: by_id[build_id].duration_units for build_id in queue}
    predecessor: dict[str, str] = {}
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for child in sorted(children[current]):
            candidate_distance = distance[current] + by_id[child].duration_units
            if candidate_distance > distance.get(child, 0):
                distance[child] = candidate_distance
                predecessor[child] = current
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if visited != len(builds):
        raise ValueError("build dependency cycle detected")
    if not builds:
        return CriticalPathResult(ordered_build_ids=[], total_duration_units=0)
    end = max(distance, key=lambda build_id: (distance[build_id], build_id))
    path = [end]
    while end in predecessor:
        end = predecessor[end]
        path.append(end)
    path.reverse()
    return CriticalPathResult(ordered_build_ids=path, total_duration_units=distance[path[-1]])


# BUILD-BRAIN-117 — duplicate architecture detection
class ArchitectureFingerprint(StrictModel):
    architecture_id: str
    title: str
    normalized_terms: set[str] = Field(min_length=1)
    dependency_ids: set[str] = Field(default_factory=set)


class DuplicateArchitectureCandidate(StrictModel):
    left_id: str
    right_id: str
    similarity: float = Field(ge=0, le=1)
    status: Literal["candidate"] = "candidate"


def detect_duplicate_architectures(items: list[ArchitectureFingerprint], threshold: float = 0.6) -> list[DuplicateArchitectureCandidate]:
    if not 0 <= threshold <= 1:
        raise ValueError("duplicate threshold must be within [0, 1]")
    results = []
    ordered = sorted(items, key=lambda item: item.architecture_id)
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            union = left.normalized_terms | right.normalized_terms
            intersection = left.normalized_terms & right.normalized_terms
            term_similarity = 0.0 if not union else len(intersection) / len(union)
            dependency_union = left.dependency_ids | right.dependency_ids
            dependency_similarity = 0.0 if not dependency_union else len(left.dependency_ids & right.dependency_ids) / len(dependency_union)
            similarity = round((term_similarity * 0.8) + (dependency_similarity * 0.2), 8)
            if similarity >= threshold:
                results.append(DuplicateArchitectureCandidate(left_id=left.architecture_id, right_id=right.architecture_id, similarity=similarity))
    return sorted(results, key=lambda item: (-item.similarity, item.left_id, item.right_id))
