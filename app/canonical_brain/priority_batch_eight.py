from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def stable_checksum(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# BUILD-KE-308 — glossary coverage audit
class GlossaryCoverageItem(StrictModel):
    concept_id: str
    has_definition: bool
    has_evidence: bool
    has_accessible_media: bool
    has_related_concepts: bool


class GlossaryCoverageSummary(StrictModel):
    complete_ids: list[str]
    incomplete_ids: list[str]
    coverage_ratio: float = Field(ge=0, le=1)


def audit_glossary_coverage(items: list[GlossaryCoverageItem]) -> GlossaryCoverageSummary:
    complete = sorted(
        item.concept_id
        for item in items
        if item.has_definition and item.has_evidence and item.has_accessible_media and item.has_related_concepts
    )
    incomplete = sorted(item.concept_id for item in items if item.concept_id not in complete)
    ratio = 0.0 if not items else len(complete) / len(items)
    return GlossaryCoverageSummary(complete_ids=complete, incomplete_ids=incomplete, coverage_ratio=round(ratio, 8))


# BUILD-ATLAS-409 — restoration planning candidates
class RestorationSiteCandidate(StrictModel):
    site_id: str
    habitat_suitability: float = Field(ge=0, le=1)
    conservation_priority: float = Field(ge=0, le=1)
    restoration_feasibility: float = Field(ge=0, le=1)
    threat_reduction_potential: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(min_length=1)


class RestorationPlanCandidate(StrictModel):
    site_id: str
    score: float = Field(ge=0, le=1)
    evidence_ids: list[str]
    status: Literal["candidate"] = "candidate"


def rank_restoration_sites(items: list[RestorationSiteCandidate]) -> list[RestorationPlanCandidate]:
    results = [
        RestorationPlanCandidate(
            site_id=item.site_id,
            score=round(
                item.habitat_suitability * 0.3
                + item.conservation_priority * 0.3
                + item.restoration_feasibility * 0.2
                + item.threat_reduction_potential * 0.2,
                8,
            ),
            evidence_ids=sorted(set(item.evidence_ids)),
        )
        for item in items
    ]
    return sorted(results, key=lambda item: (-item.score, item.site_id))


# BUILD-RS-506 — data-quality audit manifests
class DataQualityCheck(StrictModel):
    check_id: str
    category: Literal["completeness", "validity", "consistency", "provenance", "licensing"]
    passed: bool
    evidence_ids: list[str] = Field(min_length=1)
    message: str


class DataQualityManifest(StrictModel):
    dataset_id: str
    checks: list[DataQualityCheck] = Field(min_length=1)
    failed_check_ids: list[str]
    checksum: str
    release_eligible: bool


def build_data_quality_manifest(dataset_id: str, checks: list[DataQualityCheck]) -> DataQualityManifest:
    ids = [item.check_id for item in checks]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate data-quality check IDs")
    ordered = sorted(checks, key=lambda item: item.check_id)
    failed = [item.check_id for item in ordered if not item.passed]
    return DataQualityManifest(
        dataset_id=dataset_id,
        checks=ordered,
        failed_check_ids=failed,
        checksum=stable_checksum([item.model_dump(mode="json") for item in ordered]),
        release_eligible=not failed,
    )


# BUILD-CON-606 — environmental alert candidates
class EnvironmentalReading(StrictModel):
    reading_id: str
    specimen_id: str
    variable: Literal["temperature", "humidity", "light", "moisture"]
    value: float
    observed_at: datetime
    minimum: float
    maximum: float


class EnvironmentalAlert(StrictModel):
    alert_id: str
    specimen_id: str
    reading_id: str
    variable: str
    severity: Literal["warning", "critical"]
    message: str
    status: Literal["candidate"] = "candidate"


def evaluate_environmental_reading(reading: EnvironmentalReading) -> EnvironmentalAlert | None:
    if reading.minimum > reading.maximum:
        raise ValueError("environmental range minimum cannot exceed maximum")
    if reading.minimum <= reading.value <= reading.maximum:
        return None
    distance = reading.minimum - reading.value if reading.value < reading.minimum else reading.value - reading.maximum
    span = max(abs(reading.maximum - reading.minimum), 1.0)
    severity: Literal["warning", "critical"] = "critical" if distance / span >= 0.5 else "warning"
    direction = "below" if reading.value < reading.minimum else "above"
    return EnvironmentalAlert(
        alert_id=f"env-alert:{reading.reading_id}",
        specimen_id=reading.specimen_id,
        reading_id=reading.reading_id,
        variable=reading.variable,
        severity=severity,
        message=f"{reading.variable} is {direction} the candidate range",
    )


# BUILD-MATRIX-706 — character information gain
class CharacterPartition(StrictModel):
    character_id: str
    state_to_taxa: dict[str, list[str]]


class CharacterInformationScore(StrictModel):
    character_id: str
    distinct_states: int
    largest_partition: int
    score: float


def rank_character_information(items: list[CharacterPartition]) -> list[CharacterInformationScore]:
    scores: list[CharacterInformationScore] = []
    for item in items:
        groups = [set(values) for values in item.state_to_taxa.values() if values]
        distinct = len(groups)
        total = len(set().union(*groups)) if groups else 0
        largest = max((len(group) for group in groups), default=0)
        score = 0.0 if total == 0 else 1 - (largest / total)
        scores.append(
            CharacterInformationScore(
                character_id=item.character_id,
                distinct_states=distinct,
                largest_partition=largest,
                score=round(score, 8),
            )
        )
    return sorted(scores, key=lambda item: (-item.score, -item.distinct_states, item.character_id))


# BUILD-VISION-806 — damage and disease observation candidates
class DamageObservationCandidate(StrictModel):
    observation_id: str
    image_id: str
    region_id: str
    category: Literal["mechanical", "pest", "disease", "nutritional", "environmental", "unknown"]
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(min_length=1)
    status: Literal["candidate"] = "candidate"


def rank_damage_observations(items: list[DamageObservationCandidate]) -> list[DamageObservationCandidate]:
    ids = [item.observation_id for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate damage-observation IDs")
    return sorted(items, key=lambda item: (-item.confidence, item.category, item.observation_id))


# BUILD-PUB-906 — evidence-backed article assembly
class ArticleSection(StrictModel):
    section_id: str
    heading: str
    body: str
    evidence_ids: list[str] = Field(min_length=1)


class ArticlePackage(StrictModel):
    article_id: str
    title: str
    sections: list[ArticleSection] = Field(min_length=1)
    checksum: str
    publication_enabled: bool = False


def assemble_article(article_id: str, title: str, sections: list[ArticleSection]) -> ArticlePackage:
    ids = [item.section_id for item in sections]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate article section IDs")
    ordered = sorted(sections, key=lambda item: item.section_id)
    return ArticlePackage(
        article_id=article_id,
        title=title,
        sections=ordered,
        checksum=stable_checksum([item.model_dump(mode="json") for item in ordered]),
    )


# BUILD-INT-957 — integration retry policy
class RetryPolicy(StrictModel):
    policy_id: str
    maximum_attempts: int = Field(ge=1, le=10)
    base_delay_seconds: int = Field(ge=1, le=3600)
    maximum_delay_seconds: int = Field(ge=1, le=86400)

    def delay_for_attempt(self, attempt: int) -> int:
        if attempt < 1 or attempt > self.maximum_attempts:
            raise ValueError("retry attempt is outside policy bounds")
        return min(self.base_delay_seconds * (2 ** (attempt - 1)), self.maximum_delay_seconds)


# BUILD-MC-207 — portfolio trend snapshots
class PortfolioMetricSnapshot(StrictModel):
    snapshot_id: str
    observed_at: datetime
    admitted: int = Field(ge=0)
    running: int = Field(ge=0)
    blocked: int = Field(ge=0)
    completed: int = Field(ge=0)


class PortfolioTrend(StrictModel):
    earlier_snapshot_id: str
    later_snapshot_id: str
    admitted_change: int
    running_change: int
    blocked_change: int
    completed_change: int


def compare_portfolio_snapshots(earlier: PortfolioMetricSnapshot, later: PortfolioMetricSnapshot) -> PortfolioTrend:
    if earlier.observed_at >= later.observed_at:
        raise ValueError("later portfolio snapshot must occur after earlier snapshot")
    return PortfolioTrend(
        earlier_snapshot_id=earlier.snapshot_id,
        later_snapshot_id=later.snapshot_id,
        admitted_change=later.admitted - earlier.admitted,
        running_change=later.running - earlier.running,
        blocked_change=later.blocked - earlier.blocked,
        completed_change=later.completed - earlier.completed,
    )


# BUILD-BRAIN-119 — architecture dependency impact analysis
class ArchitectureDependency(StrictModel):
    source_id: str
    target_id: str


class DependencyImpactReport(StrictModel):
    changed_architecture_id: str
    directly_affected_ids: list[str]
    transitively_affected_ids: list[str]


def analyze_dependency_impact(changed_architecture_id: str, dependencies: list[ArchitectureDependency]) -> DependencyImpactReport:
    reverse: dict[str, set[str]] = {}
    for item in dependencies:
        reverse.setdefault(item.target_id, set()).add(item.source_id)
    direct = sorted(reverse.get(changed_architecture_id, set()))
    visited: set[str] = set()
    stack = list(direct)
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        stack.extend(sorted(reverse.get(current, set()) - visited))
    return DependencyImpactReport(
        changed_architecture_id=changed_architecture_id,
        directly_affected_ids=direct,
        transitively_affected_ids=sorted(visited),
    )
