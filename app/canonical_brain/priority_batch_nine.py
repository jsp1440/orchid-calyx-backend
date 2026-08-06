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


# BUILD-KE-309 — glossary editorial review
class GlossaryEditorialItem(StrictModel):
    concept_id: str
    definition: str
    evidence_ids: list[str] = Field(min_length=1)
    media_ids: list[str] = Field(default_factory=list)
    reviewer_status: Literal["draft", "approved", "changes_requested"] = "draft"
    reviewer_notes: str = ""


def assess_glossary_editorial_readiness(item: GlossaryEditorialItem) -> list[str]:
    gaps: list[str] = []
    if len(item.definition.strip()) < 30:
        gaps.append("definition_too_short")
    if not item.media_ids:
        gaps.append("missing_media")
    if item.reviewer_status != "approved":
        gaps.append("editorial_review_pending")
    return gaps


# BUILD-ATLAS-410 — threat overlay candidates
class ThreatObservation(StrictModel):
    cell_id: str
    threat_type: Literal["land_use", "fire", "climate", "collection", "invasive", "pollution", "other"]
    severity: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    evidence_id: str


class ThreatOverlayCell(StrictModel):
    cell_id: str
    threat_score: float = Field(ge=0, le=1)
    threat_types: list[str]
    evidence_ids: list[str]
    status: Literal["candidate"] = "candidate"


def build_threat_overlay(observations: list[ThreatObservation]) -> list[ThreatOverlayCell]:
    grouped: dict[str, list[ThreatObservation]] = defaultdict(list)
    for item in observations:
        grouped[item.cell_id].append(item)
    results: list[ThreatOverlayCell] = []
    for cell_id, items in sorted(grouped.items()):
        weighted = sum(item.severity * item.confidence for item in items)
        denominator = sum(item.confidence for item in items)
        score = 0.0 if denominator == 0 else weighted / denominator
        results.append(ThreatOverlayCell(
            cell_id=cell_id,
            threat_score=round(score, 8),
            threat_types=sorted({item.threat_type for item in items}),
            evidence_ids=sorted({item.evidence_id for item in items}),
        ))
    return results


# BUILD-RS-507 — dataset lineage manifests
class DatasetLineageNode(StrictModel):
    dataset_id: str
    checksum: str = Field(min_length=64, max_length=64)
    parent_dataset_ids: list[str] = Field(default_factory=list)
    transformation: str
    source_uri: str


class DatasetLineageManifest(StrictModel):
    ordered_dataset_ids: list[str]
    checksum: str


def build_dataset_lineage_manifest(nodes: list[DatasetLineageNode]) -> DatasetLineageManifest:
    by_id = {node.dataset_id: node for node in nodes}
    if len(by_id) != len(nodes):
        raise ValueError("duplicate dataset IDs")
    indegree = {node.dataset_id: 0 for node in nodes}
    children: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        for parent in node.parent_dataset_ids:
            if parent not in by_id:
                raise ValueError(f"missing parent dataset: {parent}")
            indegree[node.dataset_id] += 1
            children[parent].append(node.dataset_id)
    queue = deque(sorted(item for item, degree in indegree.items() if degree == 0))
    ordered: list[str] = []
    while queue:
        current = queue.popleft()
        ordered.append(current)
        for child in sorted(children[current]):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(ordered) != len(nodes):
        raise ValueError("dataset lineage contains a cycle")
    return DatasetLineageManifest(
        ordered_dataset_ids=ordered,
        checksum=stable_checksum([by_id[item].model_dump(mode="json") for item in ordered]),
    )


# BUILD-CON-607 — governed location moves
class LocationMove(StrictModel):
    move_id: str
    specimen_id: str
    from_location: str
    to_location: str
    moved_at: datetime
    reason: str
    sensor_snapshot_id: str | None = None


class LocationMoveLedger:
    def __init__(self) -> None:
        self._moves: dict[str, LocationMove] = {}

    def register(self, move: LocationMove) -> LocationMove:
        if move.from_location == move.to_location:
            raise ValueError("location move requires a different destination")
        existing = self._moves.get(move.move_id)
        if existing and existing != move:
            raise ValueError("conflicting location-move identity")
        self._moves[move.move_id] = move
        return move

    def history(self, specimen_id: str) -> list[LocationMove]:
        return sorted(
            [item for item in self._moves.values() if item.specimen_id == specimen_id],
            key=lambda item: (item.moved_at, item.move_id),
        )


# BUILD-MATRIX-707 — hybrid ambiguity detection
class ParentProfile(StrictModel):
    taxon_id: str
    states: dict[str, str | None]


class HybridAmbiguityResult(StrictModel):
    observed_taxon_id: str
    parent_a_id: str
    parent_b_id: str
    parent_a_matches: int
    parent_b_matches: int
    ambiguous_character_ids: list[str]
    status: Literal["candidate"] = "candidate"


def assess_hybrid_ambiguity(observed_taxon_id: str, observed: dict[str, str], parent_a: ParentProfile, parent_b: ParentProfile) -> HybridAmbiguityResult:
    a_matches = b_matches = 0
    ambiguous: list[str] = []
    for character_id, value in observed.items():
        a_value = parent_a.states.get(character_id)
        b_value = parent_b.states.get(character_id)
        a_match = a_value == value
        b_match = b_value == value
        a_matches += int(a_match)
        b_matches += int(b_match)
        if a_match == b_match:
            ambiguous.append(character_id)
    return HybridAmbiguityResult(
        observed_taxon_id=observed_taxon_id,
        parent_a_id=parent_a.taxon_id,
        parent_b_id=parent_b.taxon_id,
        parent_a_matches=a_matches,
        parent_b_matches=b_matches,
        ambiguous_character_ids=sorted(ambiguous),
    )


# BUILD-VISION-807 — figure validation candidates
class FigureLabel(StrictModel):
    label_id: str
    text: str
    target_region_id: str
    evidence_id: str


class FigureValidationResult(StrictModel):
    figure_id: str
    duplicate_label_ids: list[str]
    missing_evidence_label_ids: list[str]
    unlabeled_region_ids: list[str]
    ready_for_review: bool


def validate_scientific_figure(figure_id: str, region_ids: list[str], labels: list[FigureLabel]) -> FigureValidationResult:
    counts: dict[str, int] = defaultdict(int)
    for label in labels:
        counts[label.label_id] += 1
    duplicate_ids = sorted(item for item, count in counts.items() if count > 1)
    missing_evidence = sorted(label.label_id for label in labels if not label.evidence_id.strip())
    labeled_regions = {label.target_region_id for label in labels}
    unlabeled = sorted(set(region_ids) - labeled_regions)
    return FigureValidationResult(
        figure_id=figure_id,
        duplicate_label_ids=duplicate_ids,
        missing_evidence_label_ids=missing_evidence,
        unlabeled_region_ids=unlabeled,
        ready_for_review=not duplicate_ids and not missing_evidence and not unlabeled,
    )


# BUILD-PUB-907 — publication release packets
class ReleaseArtifact(StrictModel):
    artifact_id: str
    checksum: str = Field(min_length=64, max_length=64)
    license: str


class PublicationReleasePacket(StrictModel):
    packet_id: str
    artifact_ids: list[str]
    required_review_classes: list[str]
    approved_review_classes: list[str]
    checksum: str
    release_enabled: bool = False


def build_publication_release_packet(packet_id: str, artifacts: list[ReleaseArtifact], required_reviews: list[str], approved_reviews: list[str]) -> PublicationReleasePacket:
    ids = [item.artifact_id for item in artifacts]
    if not artifacts or len(ids) != len(set(ids)):
        raise ValueError("release packet artifacts must be non-empty and unique")
    ordered = sorted(artifacts, key=lambda item: item.artifact_id)
    return PublicationReleasePacket(
        packet_id=packet_id,
        artifact_ids=[item.artifact_id for item in ordered],
        required_review_classes=sorted(set(required_reviews)),
        approved_review_classes=sorted(set(approved_reviews)),
        checksum=stable_checksum([item.model_dump(mode="json") for item in ordered]),
        release_enabled=False,
    )


# BUILD-INT-958 — integration observability
class IntegrationMetric(StrictModel):
    contract_id: str
    attempted: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    dead_lettered: int = Field(ge=0)


class IntegrationHealth(StrictModel):
    contract_id: str
    success_rate: float = Field(ge=0, le=1)
    failure_rate: float = Field(ge=0, le=1)
    dead_letter_rate: float = Field(ge=0, le=1)


def summarize_integration_health(metric: IntegrationMetric) -> IntegrationHealth:
    if metric.succeeded + metric.failed != metric.attempted:
        raise ValueError("attempt counts must equal succeeded plus failed")
    denominator = metric.attempted or 1
    return IntegrationHealth(
        contract_id=metric.contract_id,
        success_rate=metric.succeeded / denominator,
        failure_rate=metric.failed / denominator,
        dead_letter_rate=metric.dead_lettered / denominator,
    )


# BUILD-MC-208 — dependency heatmap projection
class DependencyEdge(StrictModel):
    source_id: str
    target_id: str


class DependencyHeat(StrictModel):
    object_id: str
    inbound: int
    outbound: int
    total: int


def build_dependency_heatmap(edges: list[DependencyEdge]) -> list[DependencyHeat]:
    inbound: dict[str, int] = defaultdict(int)
    outbound: dict[str, int] = defaultdict(int)
    objects: set[str] = set()
    for edge in edges:
        if edge.source_id == edge.target_id:
            raise ValueError("self dependencies are not allowed")
        objects.update([edge.source_id, edge.target_id])
        outbound[edge.source_id] += 1
        inbound[edge.target_id] += 1
    return sorted(
        [DependencyHeat(object_id=item, inbound=inbound[item], outbound=outbound[item], total=inbound[item] + outbound[item]) for item in objects],
        key=lambda item: (-item.total, item.object_id),
    )


# BUILD-BRAIN-120 — roadmap consistency checks
class RoadmapBuild(StrictModel):
    build_id: str
    priority: int = Field(ge=1)
    dependency_ids: list[str] = Field(default_factory=list)
    status: Literal["planned", "active", "completed", "blocked"]


class RoadmapConsistencyReport(StrictModel):
    duplicate_ids: list[str]
    missing_dependency_ids: list[str]
    completed_before_dependency_ids: list[str]
    consistent: bool


def audit_roadmap_consistency(builds: list[RoadmapBuild]) -> RoadmapConsistencyReport:
    counts: dict[str, int] = defaultdict(int)
    for build in builds:
        counts[build.build_id] += 1
    duplicates = sorted(item for item, count in counts.items() if count > 1)
    by_id = {build.build_id: build for build in builds}
    missing = sorted({dependency for build in builds for dependency in build.dependency_ids if dependency not in by_id})
    premature = sorted(
        build.build_id
        for build in builds
        if build.status == "completed" and any(by_id[dependency].status != "completed" for dependency in build.dependency_ids if dependency in by_id)
    )
    return RoadmapConsistencyReport(
        duplicate_ids=duplicates,
        missing_dependency_ids=missing,
        completed_before_dependency_ids=premature,
        consistent=not duplicates and not missing and not premature,
    )
