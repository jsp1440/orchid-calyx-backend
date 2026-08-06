from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict, deque
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def stable_checksum(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# BUILD-BRAIN-110 — dependency-aware scheduling
class ScheduledBuild(StrictModel):
    build_id: str = Field(min_length=3)
    priority: int = Field(ge=1, le=100)
    dependencies: list[str] = Field(default_factory=list)
    completed: bool = False


class DependencyScheduler:
    def order(self, builds: list[ScheduledBuild]) -> list[str]:
        by_id = {item.build_id: item for item in builds}
        if len(by_id) != len(builds):
            raise ValueError("duplicate build IDs")
        for item in builds:
            missing = sorted(set(item.dependencies) - set(by_id))
            if missing:
                raise ValueError(f"missing dependencies for {item.build_id}: {missing}")
        indegree = {item.build_id: 0 for item in builds}
        children: dict[str, list[str]] = defaultdict(list)
        for item in builds:
            for dependency in item.dependencies:
                indegree[item.build_id] += 1
                children[dependency].append(item.build_id)
        ready = sorted(
            [by_id[item_id] for item_id, degree in indegree.items() if degree == 0],
            key=lambda item: (item.priority, item.build_id),
        )
        ordered: list[str] = []
        queue = deque(ready)
        while queue:
            current = queue.popleft()
            ordered.append(current.build_id)
            newly_ready: list[ScheduledBuild] = []
            for child in children[current.build_id]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    newly_ready.append(by_id[child])
            queue.extend(sorted(newly_ready, key=lambda item: (item.priority, item.build_id)))
        if len(ordered) != len(builds):
            raise ValueError("dependency cycle detected")
        return ordered


# BUILD-BRAIN-111 — evidence and artifact registry
class ArtifactRecord(StrictModel):
    artifact_id: str = Field(min_length=3)
    media_type: str = Field(min_length=3)
    source_uri: str = Field(min_length=3)
    license: str = Field(min_length=2)
    producer_assignment_id: str = Field(min_length=3)
    content_checksum: str = Field(min_length=64, max_length=64)
    supersedes_id: str | None = None


class ArtifactRegistry:
    def __init__(self) -> None:
        self._records: dict[str, ArtifactRecord] = {}
        self._checksums: dict[str, str] = {}

    def register(self, record: ArtifactRecord) -> ArtifactRecord:
        existing = self._records.get(record.artifact_id)
        if existing and existing != record:
            raise ValueError("conflicting artifact identity")
        checksum_owner = self._checksums.get(record.content_checksum)
        if checksum_owner and checksum_owner != record.artifact_id:
            raise ValueError(f"duplicate content already registered as {checksum_owner}")
        if record.supersedes_id and record.supersedes_id not in self._records:
            raise ValueError("superseded artifact is not registered")
        self._records[record.artifact_id] = record
        self._checksums[record.content_checksum] = record.artifact_id
        return record

    def list(self) -> list[ArtifactRecord]:
        return sorted(self._records.values(), key=lambda item: item.artifact_id)


# BUILD-BRAIN-112 — review and release eligibility
ReviewClass = Literal["scientific", "licensing", "security", "operational"]
ReviewDecision = Literal["approved", "rejected", "changes_requested"]


class ReviewRecord(StrictModel):
    review_id: str = Field(min_length=3)
    artifact_id: str = Field(min_length=3)
    review_class: ReviewClass
    reviewer_id: str = Field(min_length=3)
    producer_id: str = Field(min_length=3)
    decision: ReviewDecision

    @model_validator(mode="after")
    def prevent_self_approval(self) -> ReviewRecord:
        if self.decision == "approved" and self.reviewer_id == self.producer_id:
            raise ValueError("producers cannot approve their own artifacts")
        return self


class ReviewGate:
    def release_eligible(self, records: list[ReviewRecord], required: set[ReviewClass]) -> bool:
        approved = {item.review_class for item in records if item.decision == "approved"}
        blocking = any(item.decision in {"rejected", "changes_requested"} for item in records)
        return not blocking and required.issubset(approved)


# BUILD-BRAIN-113 — automatic Brain capture
class CaptureCandidate(StrictModel):
    build_id: str
    artifact_ids: list[str] = Field(min_length=1)
    validation_ids: list[str] = Field(min_length=1)
    source_uris: list[str] = Field(min_length=1)


def brain_capture_manifest(candidate: CaptureCandidate) -> dict[str, object]:
    payload = candidate.model_dump(mode="json")
    return {
        "record_id": f"build:{candidate.build_id}",
        "object_type": "build",
        "payload": payload,
        "checksum": stable_checksum(payload),
        "publication_enabled": False,
    }


# BUILD-MC-200 — portfolio projection
class PortfolioItem(StrictModel):
    build_id: str
    architecture_id: str
    status: str
    blocked_reason: str | None = None
    next_action: str


def portfolio_projection(items: list[PortfolioItem]) -> dict[str, object]:
    ordered = sorted(items, key=lambda item: (item.architecture_id, item.build_id))
    return {
        "items": [item.model_dump(mode="json") for item in ordered],
        "counts": dict(sorted({status: sum(item.status == status for item in ordered) for status in {item.status for item in ordered}}.items())),
        "write_enabled": False,
    }


# BUILD-KE-300 — Knowledge Explorer vertical slice
class KnowledgeConcept(StrictModel):
    concept_id: str
    preferred_term: str
    synonyms: list[str] = Field(default_factory=list)
    concise_definition: str
    detailed_definition: str
    evidence_uris: list[str] = Field(min_length=1)
    related_concept_ids: list[str] = Field(default_factory=list)
    review_status: Literal["candidate", "approved"] = "candidate"


def velamen_fixture() -> list[KnowledgeConcept]:
    return [
        KnowledgeConcept(
            concept_id="concept:velamen",
            preferred_term="velamen",
            synonyms=["velamen radicum"],
            concise_definition="A multilayered outer root tissue common in many epiphytic orchids.",
            detailed_definition="The velamen is a specialized, usually dead-at-maturity outer root tissue that participates in rapid water interception, mechanical protection, and interactions with the root surface environment.",
            evidence_uris=["evidence://knowledge-explorer/velamen/1"],
            related_concept_ids=["concept:exodermis", "concept:passage-cell"],
        ),
        KnowledgeConcept(
            concept_id="concept:exodermis",
            preferred_term="exodermis",
            concise_definition="A cortical boundary layer beneath the velamen.",
            detailed_definition="The exodermis regulates movement into the inner cortex and may contain specialized passage cells.",
            evidence_uris=["evidence://knowledge-explorer/exodermis/1"],
            related_concept_ids=["concept:velamen", "concept:passage-cell"],
        ),
        KnowledgeConcept(
            concept_id="concept:passage-cell",
            preferred_term="passage cell",
            concise_definition="A less-suberized cell that permits transport across a boundary layer.",
            detailed_definition="Passage cells in orchid roots are associated with regulated movement through the exodermis.",
            evidence_uris=["evidence://knowledge-explorer/passage-cell/1"],
            related_concept_ids=["concept:exodermis"],
        ),
    ]


# BUILD-FIG-301 — FigureLabs assisted gateway
class FigureBrief(StrictModel):
    brief_id: str
    title: str
    required_labels: list[str] = Field(min_length=1)
    source_uris: list[str] = Field(min_length=1)
    output_formats: list[Literal["svg", "pptx", "png"]] = Field(min_length=1)
    provider: str = "FigureLabs-assisted"
    publication_status: Literal["candidate"] = "candidate"


def orchid_root_figure_brief() -> FigureBrief:
    return FigureBrief(
        brief_id="figure-brief:orchid-root-velamen-v1",
        title="Orchid Root and Velamen Plate",
        required_labels=["root tip", "velamen", "exodermis", "passage cells", "cortex", "endodermis", "stele"],
        source_uris=["evidence://knowledge-explorer/velamen/1"],
        output_formats=["svg", "pptx", "png"],
    )


# BUILD-ATLAS-400 — thematic-map execution slice
class AtlasLayer(StrictModel):
    layer_id: str
    category: Literal["biodiversity", "earth_science", "conservation", "sampling"]
    dataset_uri: str
    crs: str
    checksum: str = Field(min_length=64, max_length=64)


def atlas_manifest(layers: list[AtlasLayer]) -> dict[str, object]:
    categories = {item.category for item in layers}
    required = {"biodiversity", "earth_science", "conservation", "sampling"}
    if not required.issubset(categories):
        raise ValueError("Atlas vertical slice requires all four layer categories")
    ordered = sorted(layers, key=lambda item: (item.category, item.layer_id))
    payload = [item.model_dump(mode="json") for item in ordered]
    return {
        "map_id": "atlas-map:vertical-slice-v1",
        "layers": payload,
        "checksum": stable_checksum(payload),
        "publication_enabled": False,
    }


# BUILD-KE-302 — contextual terminology recognition
class TermMatch(StrictModel):
    concept_id: str
    term: str
    start: int
    end: int


def recognize_terms(text: str, concepts: list[KnowledgeConcept]) -> list[TermMatch]:
    matches: list[TermMatch] = []
    for concept in concepts:
        for term in [concept.preferred_term, *concept.synonyms]:
            for match in re.finditer(rf"\b{re.escape(term)}\b", text, flags=re.IGNORECASE):
                matches.append(TermMatch(concept_id=concept.concept_id, term=match.group(0), start=match.start(), end=match.end()))
    return sorted(matches, key=lambda item: (item.start, -(item.end - item.start), item.concept_id))


# BUILD-FIG-303 — visual asset registry and Living Figures
class LivingFigure(StrictModel):
    figure_id: str
    version: int = Field(ge=1)
    asset_ids: list[str] = Field(min_length=1)
    concept_ids: list[str] = Field(min_length=1)
    evidence_uris: list[str] = Field(min_length=1)
    review_status: Literal["candidate", "approved"] = "candidate"
    supersedes_version: int | None = None

    @model_validator(mode="after")
    def validate_version_lineage(self) -> LivingFigure:
        if self.version > 1 and self.supersedes_version != self.version - 1:
            raise ValueError("Living Figure versions must supersede the immediately prior version")
        return self


class LivingFigureRegistry:
    def __init__(self) -> None:
        self._versions: dict[str, list[LivingFigure]] = defaultdict(list)

    def register(self, figure: LivingFigure) -> LivingFigure:
        versions = self._versions[figure.figure_id]
        if versions and figure.version != versions[-1].version + 1:
            raise ValueError("Living Figure versions must be sequential")
        if not versions and figure.version != 1:
            raise ValueError("first Living Figure version must be 1")
        versions.append(figure)
        return figure

    def latest(self, figure_id: str) -> LivingFigure | None:
        versions = self._versions.get(figure_id, [])
        return versions[-1] if versions else None
